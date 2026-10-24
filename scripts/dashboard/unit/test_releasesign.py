"""releasesign.py (R106): a release's APK built unsigned in CI and signed on
the project's node with its sideload key. Against a stand-in for
GitHub's API, its artifact storage and its upload host on a local port: the
run's bb-release-apk-TAG artifact is fetched (its storage never handed the
token), each APK signed and attached under its name less -unsigned with its
sha256 and a notes line giving the key's fingerprint, a second look signs
nothing twice, and a failure is kept for the bell and signed again on a
press. What would stop a release is said before it: no key, an app mapped
to none of several, the project's node offline or without its tools. Where
a toolchain store with the jdk and build-tools is here, a real APK is signed
end to end by the real agent's side of the job (signnode.py)."""
import glob
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import cilogs  # noqa: E402
import forgerelease  # noqa: E402
import releasesign  # noqa: E402
import signing  # noqa: E402
import signnode  # noqa: E402

SEEN = []
REL = {}
FLOW = """name: android app
on: {release: {types: [published]}}
jobs:
  build:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9   # v7.0.2
        with:
          name: bb-release-apk-${{ github.event.release.tag_name }}
"""
GRADLE = 'android {\n    defaultConfig {\n        applicationId = "dev.example.app"\n    }\n}\n'


def artifact_zip():
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("app-0.7.0-unsigned.apk", b"unsigned apk bytes")
    return b.getvalue()


class GitHub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def answer(self, body, code=200, raw=None, ctype="application/json"):
        data = raw if raw is not None else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        p = self.path
        SEEN.append(("GET", p, self.headers.get("Authorization")))
        if p.startswith("/storage/"):
            # GitHub's storage host: it must never be handed the token.
            return self.answer(None, raw=artifact_zip(), ctype="application/zip")
        if self.headers.get("Authorization") != "Bearer tok":
            return self.answer({"message": "Bad credentials"}, 401)
        if p.startswith("/repos/o/app/actions/runs?"):
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            return self.answer({"workflow_runs": [
                {"id": 21, "event": "release", "head_branch": "v0.7.0", "created_at": now},
                {"id": 20, "event": "push", "head_branch": "main", "created_at": now},
                {"id": 9, "event": "release", "head_branch": "v0.1.0", "created_at": "2020-01-01T00:00:00Z"}]})
        if p.startswith("/repos/o/app/actions/runs/21/artifacts"):
            return self.answer({"artifacts": [{"id": 77, "name": "bb-release-apk-v0.7.0", "expired": False},
                                              {"id": 78, "name": "something-else", "expired": False}]})
        if p.startswith("/repos/o/app/actions/runs/"):
            return self.answer({"artifacts": []})
        if p == "/repos/o/app/actions/artifacts/77/zip":
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_address[1]}/storage/77.zip")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        if p.startswith("/repos/o/app/releases/tags/"):
            tag = p.rsplit("/", 1)[-1]
            return self.answer(REL[tag]) if tag in REL else self.answer({"message": "Not Found"}, 404)
        return self.answer({"message": "Not Found"}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n)
        SEEN.append(("POST", self.path, raw))
        if self.path.startswith("/repos/o/app/releases/7/assets?name="):
            name = self.path.split("name=", 1)[1]
            REL["v0.7.0"]["assets"].append({"id": len(REL["v0.7.0"]["assets"]) + 100, "name": name})
            return self.answer({"id": 1, "browser_download_url": f"https://github.com/o/app/{name}"}, 201)
        return self.answer({"message": "Not Found"}, 404)

    def do_PATCH(self):
        n = int(self.headers.get("Content-Length") or 0)
        b = json.loads(self.rfile.read(n))
        SEEN.append(("PATCH", self.path, b))
        REL["v0.7.0"]["body"] = b["body"]
        return self.answer(REL["v0.7.0"])

    def do_DELETE(self):
        SEEN.append(("DELETE", self.path, None))
        aid = int(self.path.rsplit("/", 1)[-1])
        REL["v0.7.0"]["assets"] = [a for a in REL["v0.7.0"]["assets"] if a["id"] != aid]
        self.send_response(204)
        self.end_headers()


class Base(unittest.TestCase):
    def setUp(self):
        SEEN.clear(); REL.clear()
        REL["v0.7.0"] = {"id": 7, "html_url": "https://github.com/o/app/releases/tag/v0.7.0",
                         "body": "### Added\n\n- A thing\n\nSigned by BuilderBot: an old line",
                         "assets": [{"id": 5, "name": "app-0.7.0.apk"}]}
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), GitHub)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        app = self.tmp / "ws" / "app"
        (app / ".github" / "workflows").mkdir(parents=True)
        (app / ".github" / "workflows" / "android.yml").write_text(FLOW)
        (app / "app").mkdir()
        (app / "app" / "build.gradle.kts").write_text(GRADLE)
        (self.tmp / "gitcreds").mkdir()
        (self.tmp / "gitcreds" / "app").write_text("https://x:tok@github.com\n")

        def wj(path, d):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(json.dumps(d))
        cilogs.configure(state=self.tmp, workspace=self.tmp / "ws",
                         push_record_fn={"app": {"repo": "o/app", "host": "github.com"}}.get)
        forgerelease.configure(state=self.tmp, workspace=self.tmp / "ws", write_json_fn=wj)
        releasesign.configure(state=self.tmp, workspace=self.tmp / "ws", write_json_fn=wj, projects=lambda: ["app"])
        signing.configure(state=self.tmp / "state", project_name=re.compile(r"[A-Za-z0-9._-]+"))
        # The project's node, there and ready unless a test says otherwise.
        for k in ("node_of", "node_get", "node_tools", "node_refuses"):
            self.addCleanup(setattr, signing, k, getattr(signing, k))
        signing.node_of = lambda p: "n_1"
        signing.node_get = signing.node_tools = signing.node_refuses = None
        base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        for mod, k in ((cilogs, "API"), (forgerelease, "API"), (forgerelease, "UPLOADS")):
            self.addCleanup(setattr, mod, k, getattr(mod, k))
            setattr(mod, k, base)
        # A kept sideload key, as signing.py writes one (its keystore is not
        # opened here: sign_release is stood in for, below).
        self.key("default")
        self.signed, self.fail_why = [], ""

        def fake_sign(project, src, out):
            self.signed.append((project, Path(src).read_bytes()))
            if self.fail_why:
                return {"error": self.fail_why}
            Path(out).write_bytes(b"signed:" + Path(src).read_bytes())
            return {"key": "default", "cert": "AB:CD", "package": "dev.example.app", "schemes": ["v2"]}
        self.addCleanup(setattr, signing, "sign_release", signing.sign_release)
        signing.sign_release = fake_sign

    def key(self, name, sha="AB:CD"):
        d = self.tmp / "state" / "signing" / "app" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "sideload.ks").write_bytes(b"ks")
        (d / "sideload.json").write_text(json.dumps({"route": "sideload", "key": name, "alias": name,
                                                     "sha256": sha, "store_pass": "p"}))
        releasesign._cache.clear()


class Signs(Base):
    def test_the_runs_unsigned_apk_is_signed_and_attached_with_its_fingerprint(self):
        r = releasesign.check("app")
        self.assertEqual(r["signed"], ["v0.7.0"], r)
        self.assertEqual(self.signed, [("app", b"unsigned apk bytes")])
        # The storage host was never handed the token.
        self.assertEqual([a for m, p, a in SEEN if p.startswith("/storage/")], [None])
        ups = {p.split("name=", 1)[1]: raw for m, p, raw in SEEN if m == "POST"}
        self.assertEqual(sorted(ups), ["app-0.7.0.apk", "app-0.7.0.apk.sha256"])
        self.assertEqual(ups["app-0.7.0.apk"], b"signed:unsigned apk bytes")
        want = hashlib.sha256(b"signed:unsigned apk bytes").hexdigest()
        self.assertEqual(ups["app-0.7.0.apk.sha256"].decode(), f"{want}  app-0.7.0.apk\n")
        # One of the same name was replaced, not left beside it.
        self.assertIn(("DELETE", "/repos/o/app/releases/assets/5", None), SEEN)
        body = REL["v0.7.0"]["body"]
        self.assertIn("### Added\n\n- A thing", body)
        self.assertNotIn("an old line", body)
        self.assertTrue(body.endswith("Signed by BuilderBot: app-0.7.0.apk with the sideload key default, "
                                      "certificate SHA-256 AB:CD"), body)
        st = releasesign.status("app")
        self.assertEqual(st["signed"][0]["tag"], "v0.7.0")
        self.assertEqual(st["signed"][0]["cert"], "AB:CD")
        # The run older than an artifact is kept is not asked about.
        self.assertFalse([p for m, p, a in SEEN if "/runs/9/" in p])

    def test_a_second_look_signs_nothing_twice(self):
        releasesign.check("app")
        n = len(self.signed)
        asked = len([p for m, p, a in SEEN if "/runs/20/artifacts" in p])
        self.assertEqual(releasesign.check("app")["signed"], [])
        self.assertEqual(len(self.signed), n)
        # ...and a run that handed over nothing is not asked about again.
        self.assertEqual(len([p for m, p, a in SEEN if "/runs/20/artifacts" in p]), asked)

    def test_a_failed_signing_is_said_on_the_bell_and_signed_again_on_a_press(self):
        self.fail_why = "app-0.7.0-unsigned.apk: no key"
        r = releasesign.check("app")
        self.assertEqual(r["failed"], ["v0.7.0"])
        self.assertFalse([1 for m, _, _ in SEEN if m == "POST"], "nothing is attached when signing fails")
        rows = [a for a in releasesign.attention(["app"]) if a["bad"]]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["tag"], rows[0]["kind"]), ("v0.7.0", "release-sign"))
        self.assertIn("no key", rows[0]["why"])
        self.assertTrue(rows[0]["key"].startswith("rsign:app|v0.7.0@"))
        # Not tried again at once by the loop...
        self.assertEqual(releasesign.check("app")["failed"], [])
        # ...but on a press, and the red row goes once it is signed.
        self.fail_why = ""
        self.assertEqual(releasesign.check("app", force=True)["signed"], ["v0.7.0"])
        self.assertFalse([a for a in releasesign.attention(["app"]) if a["bad"]])

    def test_a_release_whose_apk_never_came_is_said(self):
        releasesign.expect("app", "v0.9.0")
        d = json.loads((self.tmp / "release-signing.json").read_text())
        d["app"]["expect"]["v0.9.0"] = int(time.time()) - releasesign.EXPECT_S - 5
        (self.tmp / "release-signing.json").write_text(json.dumps(d))
        releasesign.check("app")
        bad = [a for a in releasesign.attention(["app"]) if a["bad"]]
        self.assertEqual([a["tag"] for a in bad], ["v0.9.0"])
        self.assertIn("no run handed over an unsigned APK", bad[0]["why"])

    def test_an_expected_release_is_looked_for_at_once_and_due_until_signed(self):
        self.assertTrue(releasesign.due("app"))        # never scanned
        releasesign.check("app")
        self.assertFalse(releasesign.due("app"))
        d = json.loads((self.tmp / "release-signing.json").read_text())
        d["app"]["expect"]["v0.8.0"] = int(time.time())
        (self.tmp / "release-signing.json").write_text(json.dumps(d))
        self.assertTrue(releasesign.due("app"))


class Before(Base):
    def test_the_key_that_signs_releases_is_named(self):
        r = releasesign.readiness("app")
        self.assertTrue(r["wanted"])
        self.assertEqual(r["packages"], ["dev.example.app"])
        self.assertEqual([(k["package"], k["key"], k["sha256"]) for k in r["keys"]],
                         [("dev.example.app", "default", "AB:CD")])
        self.assertEqual(r["why"], "")
        self.assertEqual(releasesign.attention(["app"]), [])

    def test_no_sideload_key_is_said_on_the_bell_before_the_release(self):
        shutil.rmtree(self.tmp / "state" / "signing" / "app" / "default")
        releasesign._cache.clear()
        rows = releasesign.attention(["app"])
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["bad"])
        self.assertIn("has no sideload signing key", rows[0]["why"])
        self.assertTrue(rows[0]["key"].startswith("rsign:app@"))

    def test_several_keys_and_no_mapping_is_said(self):
        shutil.rmtree(self.tmp / "state" / "signing" / "app" / "default")
        self.key("watch"); self.key("phone", "EF:01")
        why = releasesign.readiness("app")["why"]
        self.assertIn("dev.example.app is mapped to no key", why)
        self.assertIn("map it in the Signing view", why)
        (self.tmp / "state" / "signing" / "app" / "map.json").write_text(json.dumps({"dev.example.app": "phone"}))
        releasesign._cache.clear()
        r = releasesign.readiness("app")
        self.assertEqual((r["why"], r["keys"][0]["key"], r["keys"][0]["sha256"]), ("", "phone", "EF:01"))

    def test_a_rotated_key_signs_releases_with_its_successor(self):
        self.key("next", "99:99")
        d = self.tmp / "state" / "signing" / "app"
        rec = json.loads((d / "default" / "sideload.json").read_text())
        (d / "default" / "sideload.json").write_text(json.dumps(rec | {"retired_for": "next"}))
        releasesign._cache.clear()
        self.assertEqual(releasesign.readiness("app")["keys"][0]["key"], "next")

    def test_the_nodes_state_is_said(self):
        # The node it is signed on, in its words: offline, or without the
        # build-tools, which a rotation's proof and an APK need.
        n = {"id": "n_1", "name": "bb-sandbox", "state": "online", "kind": "agent", "live": False}
        signing.node_get = lambda nid: n
        r = releasesign.readiness("app", fresh=True)
        self.assertIn("app's node bb-sandbox is offline", r["why"])
        self.assertEqual(r["node"], "bb-sandbox")
        n["live"] = True
        signing.node_tools = lambda node: {"jdk", "android-tools"}
        self.assertIn("has no Android SDK Build-Tools", releasesign.readiness("app", fresh=True)["why"])
        signing.node_tools = lambda node: {"jdk", "android-tools", "android:build-tools"}
        self.assertEqual(releasesign.readiness("app", fresh=True)["why"], "")

    def test_a_project_whose_workflows_hand_over_nothing_is_left_alone(self):
        (self.tmp / "ws" / "app" / ".github" / "workflows" / "android.yml").write_text("name: x\n")
        releasesign._cache.clear()
        self.assertFalse(releasesign.readiness("app")["wanted"])
        shutil.rmtree(self.tmp / "state" / "signing" / "app" / "default")
        releasesign._cache.clear()
        self.assertEqual(releasesign.attention(["app"]), [])

    def test_an_unsigned_build_is_never_one_of_a_releases_files(self):
        dist = self.tmp / "ws" / "app" / "dist"
        dist.mkdir()
        (dist / "app-0.7.0-65298e0-unsigned.apk").write_bytes(b"x")
        self.assertEqual(forgerelease.assets("app", "65298e0"), [])
        (dist / "app-0.7.0-65298e0-release.apk").write_bytes(b"x")
        self.assertEqual([f.name for f in forgerelease.assets("app", "65298e0")], ["app-0.7.0-65298e0-release.apk"])




# ---- a real APK, signed on the node with its own tools ----------------------

def jar():
    jars = sorted(glob.glob(os.path.join(signnode.STORE_BT, "android", "platforms", "android-*", "android.jar"))) \
        if signnode.STORE_BT else []
    return jars[0] if jars else ""


JAR = jar()


@unittest.skipUnless(JAR, "no toolchain store with the jdk, build-tools and a platform here")
class RealSigning(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        signing.configure(state=self.tmp / "state", project_name=re.compile(r"[A-Za-z0-9._-]+"))
        self.node = signnode.install(self, signing, str(self.tmp / "data"), store=signnode.STORE_BT)
        self.bt = os.path.dirname(signnode.agent.module("keyops").build_tools(signnode.STORE_BT)["apksigner"])
        jdk = os.path.join(signnode.STORE_BT, "jdk")
        self.env = dict(os.environ, JAVA_HOME=jdk, PATH=os.path.join(jdk, "bin") + os.pathsep + os.environ["PATH"])
        signing.set_backup_password("app", "", "a-backup-password")
        man = self.tmp / "AndroidManifest.xml"
        man.write_text('<manifest xmlns:android="http://schemas.android.com/apk/res/android" '
                       'package="dev.example.app"><uses-sdk android:minSdkVersion="26"/></manifest>')
        self.apk = self.tmp / "app-unsigned.apk"
        subprocess.run([os.path.join(self.bt, "aapt2"), "link", "-o", str(self.apk), "-I", JAR,
                        "--manifest", str(man)], check=True, capture_output=True)

    def test_an_unsigned_apk_is_signed_on_the_node_with_the_kept_key(self):
        r, st = signing.generate("app", "sideload", "default")
        self.assertEqual(st, 200, r)
        out = self.tmp / "app.apk"
        got = signing.sign_release("app", self.apk, out)
        self.assertNotIn("error", got, got)
        self.assertEqual((got["key"], got["package"]), ("default", "dev.example.app"))
        self.assertEqual(got["cert"], r["key"]["sha256"])
        v = subprocess.run([os.path.join(self.bt, "apksigner"), "verify", "--print-certs", str(out)],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(v.returncode, 0, v.stderr)
        self.assertIn(r["key"]["sha256"].replace(":", "").lower(), v.stdout.lower())
        job = [j for j in self.node.jobs.values() if j["spec"]["op"] == "release"][0]
        self.assertEqual((job["type"], job["state"]), ("sign-key", "succeeded"), job["log"])
        self.assertEqual(os.listdir(self.tmp / "data" / "sign-key"), [])
        self.assertEqual(signing._handover, {})

    def test_a_rotated_key_signs_with_the_proof(self):
        signing.generate("app", "sideload", "default")
        signing.generate("app", "sideload", "next")
        self.assertEqual(signing.rotate("app", "default", "next")[1], 200)
        got = signing.sign_release("app", self.apk, self.tmp / "app.apk")
        self.assertEqual((got.get("key"), got.get("rotated_from")), ("next", "default"), got)

    def test_no_key_is_refused_before_anything_is_signed(self):
        got = signing.sign_release("app", self.apk, self.tmp / "app.apk")
        self.assertIn("has no sideload signing key", got["error"])
        self.assertFalse((self.tmp / "app.apk").exists())


if __name__ == "__main__":
    unittest.main()
