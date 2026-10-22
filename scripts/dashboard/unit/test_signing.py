"""signing.py (R106): a project's Android keys kept by the controller and
worked on by a sign-key job on the project's node (signnode.py runs the real
agent's side against a toolchain store here), skipped where there is none: a
key is checked before it is kept, the listing carries no password, the files
are the owner's alone, and backup marks it saved. What keeps the node from
the work is said naming the node and what it lacks."""
import base64
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import signing  # noqa: E402
import signnode  # noqa: E402

# The store's keytool, for making a test's own keystore and opening one.
KT = os.path.join(signnode.STORE, "jdk", "bin", "keytool") if signnode.STORE else ""


@unittest.skipUnless(KT, "no toolchain store with a jdk on this machine")
class Signing(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        signing.configure(state=self.tmp / "state", project_name=re.compile(r"[A-Za-z0-9._-]+"))
        self.node = signnode.install(self, signing, str(self.tmp / "data"))
        # A key is kept only once its backups have a password (2 Oct).
        signing.set_backup_password("app", "", "a-backup-password")
        self.ks = self.tmp / "k.p12"
        subprocess.run([KT, "-genkeypair", "-keystore", str(self.ks), "-storetype", "PKCS12",
                        "-storepass", "s3cret-pass", "-alias", "upload", "-keyalg", "RSA",
                        "-keysize", "2048", "-validity", "100", "-dname", "CN=Test"],
                       check=True, capture_output=True)
        self.b64 = base64.b64encode(self.ks.read_bytes()).decode()

    def test_a_key_is_kept_once_keytool_reads_it(self):
        r, st = signing.put("app", "sideload", self.b64, "s3cret-pass", by="sean")
        self.assertEqual(st, 200, r)
        self.assertEqual(r["key"]["alias"], "upload")
        self.assertRegex(r["key"]["sha256"], r"^([0-9A-F]{2}:){31}[0-9A-F]{2}$")
        self.assertNotIn("store_pass", r["key"])
        d = self.tmp / "state" / "signing" / "app" / "default"
        for x in (d, d.parent, d.parent.parent):
            self.assertEqual(stat.S_IMODE(os.stat(x).st_mode), 0o700, x)
        for f in d.iterdir():
            self.assertEqual(stat.S_IMODE(os.stat(f).st_mode), 0o600, f)

    def test_a_wrong_password_is_refused_and_nothing_kept(self):
        r, st = signing.put("app", "play", self.b64, "nope")
        self.assertEqual(st, 400)
        self.assertIn("password", r["error"])
        self.assertEqual(signing.listing("app")[0]["keys"], {})

    def test_the_listing_never_carries_a_password(self):
        signing.put("app", "play", self.b64, "s3cret-pass")
        listed = signing.listing("app")[0]
        self.assertNotIn("s3cret-pass", repr(listed))
        self.assertEqual(listed["keys"]["default"]["play"]["alias"], "upload")
        self.assertIsNone(listed["keys"]["default"]["sideload"])

    def test_backup_hands_the_keystore_back_and_marks_it(self):
        signing.put("app", "sideload", self.b64, "s3cret-pass")
        self.assertEqual(signing.listing("app")[0]["keys"]["default"]["sideload"]["backed_up"], 0)
        (name, blob), st = signing.backup("app", "sideload")
        self.assertEqual(st, 200)
        self.assertEqual(name, "app-default-sideload.p12")
        self.assertEqual(blob, self.ks.read_bytes())
        self.assertGreater(signing.listing("app")[0]["keys"]["default"]["sideload"]["backed_up"], 0)

    def test_remove(self):
        signing.put("app", "play", self.b64, "s3cret-pass")
        self.assertEqual(signing.remove("app", "play")[1], 200)
        self.assertEqual(signing.remove("app", "play")[1], 404)

    def test_keys_from_before_names_become_the_default(self):
        old = self.tmp / "state" / "signing" / "older"
        old.mkdir(parents=True)
        (old / "play.ks").write_bytes(self.ks.read_bytes())
        (old / "play.json").write_text('{"alias": "upload", "sha256": "AB", "store_pass": "s3cret-pass"}')
        self.assertEqual(signing.listing("older")[0]["keys"]["default"]["play"]["alias"], "upload")
        self.assertFalse((old / "play.ks").exists())
        self.assertIsNotNone(signing.secret("older", "play"))

    def test_a_generated_key_and_an_app_mapped_to_it(self):
        r, st = signing.generate("app", "sideload", "watch", by="sean")
        self.assertEqual(st, 200, r)
        self.assertTrue(r["key"]["generated"])
        self.assertEqual(signing.generate("app", "sideload", "watch")[1], 409)
        blob, rec = signing.secret("app", "sideload", "watch")
        self.assertEqual(signing.inspect("app", blob, rec["store_pass"], "watch")[2], rec["sha256"])
        # Made on the node, by a job whose spec holds no secret, its work
        # directory gone after and nothing of the key in its log.
        made = [j for j in self.node.jobs.values() if j["spec"]["op"] == "generate"]
        self.assertEqual((made[0]["type"], made[0]["state"]), ("sign-key", "succeeded"), made[0].get("log"))
        self.assertNotIn(rec["store_pass"], repr(made[0]["spec"]) + made[0]["log"])
        self.assertEqual(os.listdir(self.tmp / "data" / "sign-key"), [])
        self.assertEqual(signing._handover, {})
        self.assertEqual(signing.set_map("app", "com.example.watch", "nope")[1], 404)
        self.assertEqual(signing.set_map("app", "not a package", "watch")[1], 400)
        self.assertEqual(signing.set_map("app", "com.example.watch", "watch")[1], 200)
        self.assertEqual(signing.key_for("app", "com.example.watch"), "watch")
        self.assertEqual(signing.key_for("app", "com.example.phone"), "default")
        self.assertEqual(signing.routes_held("app"), ["sideload"])
        # Its backup carries the password it was made with, which is in no head.
        (name, data), st = signing.backup("app", "sideload", "watch")
        self.assertEqual(name, "app-watch-sideload.zip")
        import io
        import zipfile
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            self.assertIn(rec["store_pass"], z.read("password.txt").decode())
        # Removing a key's last slot takes its mappings with it.
        signing.remove("app", "sideload", "watch")
        self.assertEqual(signing.mapping("app"), {})

    def test_a_backup_made_with_the_password_is_wrapped_under_it(self):
        # R111: Download backup with the project's backup password wraps the
        # keystore under that password, password.txt holding none, so a
        # copy of the zip is no key without it; Import takes it typed in.
        import io
        import subprocess
        import zipfile
        signing.generate("app", "sideload", "watch")
        sha = signing.listing("app")[0]["keys"]["watch"]["sideload"]["sha256"]
        (name, data), st = signing.backup("app", "sideload", "watch", password="a-backup-password")
        self.assertEqual(st, 200)
        z = zipfile.ZipFile(io.BytesIO(data))
        said = z.read("password.txt").decode()
        self.assertIn("this project's backup password", said)
        rec = signing._record("app", "sideload", "watch")
        self.assertNotIn(rec["store_pass"], said, "the key's own password is not in the backup")
        ks = next(n for n in z.namelist() if n.endswith(".p12"))
        tmp = self.tmp / "w.p12"
        tmp.write_bytes(z.read(ks))
        opens = lambda pw: subprocess.run([KT, "-list", "-keystore", str(tmp), "-storepass", pw],
                                          capture_output=True).returncode == 0
        self.assertTrue(opens("a-backup-password") and not opens(rec["store_pass"]),
                        "the keystore opens with the backup password and not with the key's own")
        signing.set_backup_password("other", "", "another-password")
        b64 = base64.b64encode(data).decode()
        r, st = signing.import_backup("other", "", b64, filename=name)
        self.assertEqual(st, 400)
        self.assertIn("type that password", r["error"])
        r, st = signing.import_backup("other", "", b64, filename=name, password="a-backup-password")
        self.assertEqual(st, 200, r)
        self.assertEqual(signing.listing("other")[0]["keys"]["watch"]["sideload"]["sha256"], sha)

    def test_a_backup_imports_into_another_project(self):
        # R103: Download backup's zip goes into a second project as the same
        # key, its password and alias read from password.txt.
        signing.generate("app", "sideload", "watch")
        sha = signing.listing("app")[0]["keys"]["watch"]["sideload"]["sha256"]
        (name, data), _ = signing.backup("app", "sideload", "watch")
        signing.set_backup_password("other", "", "another-password")
        b64 = base64.b64encode(data).decode()
        r, st = signing.import_backup("other", "", b64, filename=name, by="sean")
        self.assertEqual(st, 200, r)
        got = signing.listing("other")[0]["keys"]["watch"]["sideload"]
        self.assertEqual(got["sha256"], sha)
        self.assertEqual(got["alias"], "watch")
        self.assertGreater(got["backed_up"], 0)
        self.assertNotIn("store_pass", repr(r))
        # ...its own backup is a zip again, its password traveling with it.
        (name2, _), _ = signing.backup("other", "sideload", "watch")
        self.assertTrue(name2.endswith(".zip"))
        # Again is a no-op; a different key over it is refused.
        self.assertEqual(signing.import_backup("other", "sideload", b64, key="watch")[1], 200)
        r, st = signing.import_backup("other", "sideload", self.b64, key="watch", password="s3cret-pass")
        self.assertEqual(st, 409, r)
        # A bare keystore needs its password; a name without a slot needs one said.
        self.assertEqual(signing.import_backup("other", "play", self.b64)[1], 400)
        r, st = signing.import_backup("other", "", self.b64, password="s3cret-pass", filename="k.p12")
        self.assertEqual(st, 400)
        self.assertIn("slot", r["error"])
        r, st = signing.import_backup("other", "play", self.b64, key="up", password="s3cret-pass")
        self.assertEqual(st, 200, r)

    def test_a_backup_zip_holds_only_its_two_files(self):
        import io
        import zipfile
        signing.generate("app", "play")
        (_, data), _ = signing.backup("app", "play")

        def zipped(extra=None, drop=None, swap=None):
            src = zipfile.ZipFile(io.BytesIO(data))
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                for n in src.namelist():
                    if n != drop:
                        z.writestr(n, swap if (swap and n.endswith(".p12")) else src.read(n))
                for n, b in (extra or {}).items():
                    z.writestr(n, b)
            return base64.b64encode(buf.getvalue()).decode()
        for b64, said in [(zipped(extra={"evil.sh": "x"}), "nothing else"),
                          (zipped(drop="password.txt"), "nothing else"),
                          (zipped(swap=self.ks.read_bytes()), "password"),
                          (base64.b64encode(b"PK\x03\x04junk").decode(), "did not open")]:
            r, st = signing.import_backup("app", "sideload", b64, key="copy")
            self.assertEqual(st, 400, r)
            self.assertIn(said, r["error"])
        self.assertIsNone(signing.listing("app")[0]["keys"].get("copy"))

    def test_no_key_until_the_backups_have_a_password(self):
        signing.set_backup_password("app2", "", "")
        r, st = signing.put("app2", "play", self.b64, "s3cret-pass")
        self.assertEqual(st, 409)
        self.assertIn("backup password", r["error"])
        self.assertEqual(signing.generate("app2", "sideload")[1], 409)

    def test_only_the_two_routes_and_a_real_project(self):
        self.assertEqual(signing.put("app", "other", self.b64, "s3cret-pass")[1], 400)
        self.assertEqual(signing.put("../x", "play", self.b64, "s3cret-pass")[1], 400)


class NodeState(unittest.TestCase):
    """What keeps the project's node from a key's work is said naming the
    node and what it lacks (B232), before any job is queued."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        signing.configure(state=self.tmp, project_name=re.compile(r"[A-Za-z0-9._-]+"))
        signing.set_backup_password("app", "", "a-backup-password")
        for k in ("node_of", "node_get", "node_tools", "node_refuses", "job_add"):
            self.addCleanup(setattr, signing, k, getattr(signing, k))
        self.n = {"id": "n_1", "name": "bb-sandbox", "state": "online", "kind": "agent", "live": True}
        self.have = {"jdk", "android-tools"}
        self.queued = []
        signing.node_of = lambda p: "n_1"
        signing.node_get = lambda nid: self.n if nid == "n_1" else None
        signing.node_tools = lambda n: self.have
        signing.node_refuses = lambda nid: ""
        signing.job_add = lambda *a, **k: self.queued.append(a) or {"error": "not queued in this test"}

    def said(self):
        r, st = signing.put("app", "play", base64.b64encode(b"x").decode(), "p")
        self.assertEqual(st, 400)
        return r["error"]

    def test_each_state_is_said(self):
        self.have = {"android-tools"}
        self.assertEqual(self.said(), "app's node bb-sandbox has no jdk: install it on its Toolchains")
        self.assertIn("no jdk", signing.listing("app")[0]["node_why"])
        self.assertEqual(signing.listing("app")[0]["node"], "bb-sandbox")
        self.n["live"] = False
        self.assertIn("app's node bb-sandbox is offline", self.said())
        self.n["live"], self.n["state"] = True, "draining"
        self.assertIn("is draining", self.said())
        self.n["state"] = "online"
        signing.node_refuses = lambda nid: "bb-sandbox runs agent 0.6.1 and this controller ships 0.6.2"
        self.assertIn("runs agent 0.6.1", self.said())
        signing.node_of = lambda p: ""
        self.assertIn("app has no node to sign on", self.said())
        self.assertEqual(self.queued, [], "nothing is queued on a node that cannot do it")

    def test_a_rotation_needs_the_build_tools_too(self):
        self.have = {"jdk", "android-tools"}
        self.assertEqual(signing.signer("app")[1], "")
        self.assertEqual(signing.signer("app", build_tools=True)[1],
                         "app's node bb-sandbox has no Android SDK Build-Tools (apksigner): install them on its Toolchains")
        # A node that has not said what its store holds is let try.
        self.have = set()
        self.assertEqual(signing.signer("app", build_tools=True)[1], "")

    def test_a_node_missing_the_jdk_says_so_through_the_job(self):
        # The store said nothing, so the job runs and its node says it.
        self.have = set()
        if not signnode.STORE:
            self.skipTest("no toolchain store here")
        signnode.install(self, signing, str(self.tmp / "data"), store=str(self.tmp / "empty"))
        signing.node_get = lambda nid: self.n
        r, st = signing.generate("app", "sideload")
        self.assertEqual(st, 409, r)
        self.assertEqual(r["error"], "app's node bb-sandbox has no jdk: install it on its Toolchains")


if __name__ == "__main__":
    unittest.main()


class Start(unittest.TestCase):
    """start() queues a sign job only for a key that exists, a build in
    dist/ and a node to sign on, and the job's spec carries no secret."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        signing.configure(state=self.tmp, project_name=re.compile(r"[A-Za-z0-9._-]+"))
        d = self.tmp / "signing" / "app"
        d.mkdir(parents=True)
        (d / "sideload.ks").write_bytes(b"k")
        (d / "sideload.json").write_text('{"alias": "a", "store_pass": "SECRET"}')
        self.queued = []
        signing.node_of = lambda p: "n_1"
        signing.file_path = lambda p, rel: Path("/x") if rel == "app-release.apk" else None
        signing.job_add = lambda pr, pl, t, spec, project="": (self.queued.append((pl, t, spec, project)) or {"ok": True, "job": "j_1"})

    def test_it_queues_the_job_with_no_secret_in_it(self):
        r, st = signing.start("user:sean", "app", "dist/app-release.apk", "sideload")
        self.assertEqual(st, 200, r)
        pl, t, spec, project = self.queued[0]
        self.assertEqual((pl, t, project), ({"node": "n_1"}, "sign", "app"))
        self.assertEqual(spec["file"], "app-release.apk")
        self.assertNotIn("SECRET", repr(spec))

    def test_a_node_whose_agent_is_behind_is_said_before_the_ask(self):
        # B515: allowed by the owner, then refused by the node.
        self.addCleanup(setattr, signing, "node_refuses", signing.node_refuses)
        signing.node_refuses = lambda nid: "n_1 runs agent 0.7.133 and this controller ships 0.7.134: press Update agent on its row first"
        r, st = signing.start("u", "app", "app-release.apk", "sideload")
        self.assertEqual(st, 409)
        self.assertIn("press Update agent", r["error"])
        self.assertEqual(self.queued, [])

    def test_refusals(self):
        self.assertIn("no Play upload key", signing.start("u", "app", "app-release.apk", "play")[0]["error"])
        self.assertIn(".apk or an .aab", signing.start("u", "app", "notes.txt", "sideload")[0]["error"])
        self.assertIn("bb build", signing.start("u", "app", "other.apk", "sideload")[0]["error"])
        signing.node_of = lambda p: ""
        self.assertIn("no node", signing.start("u", "app", "app-release.apk", "sideload")[0]["error"])
        self.assertEqual(self.queued, [])


class KeyChoice(unittest.TestCase):
    """With no key named and none called default (B509, BuilderBot's own app,
    5 Oct): the project's only key for the route signs an unmapped build,
    and when several could and none is mapped, the signing is refused
    before anybody is asked to allow it."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        signing.configure(state=self.tmp, project_name=re.compile(r"[A-Za-z0-9._-]+"))
        self.add("test")
        signing.node_of = lambda p: "n_1"
        signing.file_path = lambda p, rel: Path("/x")
        signing.job_add = lambda pr, pl, t, spec, project="": {"ok": True, "job": "j_1"}

    def add(self, name):
        d = self.tmp / "signing" / "app" / name
        d.mkdir(parents=True)
        (d / "sideload.ks").write_bytes(b"k")
        (d / "sideload.json").write_text('{"alias": "a", "store_pass": "x"}')

    def test_the_only_key_signs_an_unmapped_build(self):
        self.assertEqual(signing.key_for("app", "dev.x", "sideload"), "test")
        self.assertIsNone(signing.refusal("app", "dist/a.apk", "sideload"))

    def test_several_and_none_mapped_is_refused_before_the_ask(self):
        self.add("other")
        r = signing.refusal("app", "dist/a.apk", "sideload")
        self.assertIn("name one with --key", r[0]["error"])
        (self.tmp / "signing" / "app" / "map.json").write_text('{"dev.x": "other"}')
        self.assertIsNone(signing.refusal("app", "dist/a.apk", "sideload"), "a mapped package finds its key")
        self.assertEqual(signing.key_for("app", "dev.x", "sideload"), "other")


@unittest.skipUnless(signnode.STORE_BT, "no toolchain store with a jdk and build-tools here")
class Rotate(unittest.TestCase):
    """A sideload key rotated to another (step 7), the proof made on the
    project's node with its apksigner."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        signing.configure(state=self.tmp / "state", project_name=re.compile(r"[A-Za-z0-9._-]+"))
        self.node = signnode.install(self, signing, str(self.tmp / "data"), store=signnode.STORE_BT)
        signing.set_backup_password("app", "", "a-backup-password")
        signing.generate("app", "sideload", "default")
        signing.generate("app", "sideload", "watch2")
        signing.set_map("app", "com.example.phone", "default")

    def test_the_proof_is_kept_the_old_key_retired_and_the_apps_moved(self):
        r, st = signing.rotate("app", "default", "watch2", by="sean")
        self.assertEqual(st, 200, r)
        self.assertGreater(len(signing.lineage("app", "watch2")), 0)
        self.assertEqual(r["keys"]["default"]["sideload"]["retired_for"], "watch2")
        self.assertEqual(r["keys"]["watch2"]["sideload"]["rotated_from"], "default")
        self.assertEqual(signing.mapping("app")["com.example.phone"], "watch2")
        self.assertEqual(signing.successor("app", "default"), "watch2")
        self.assertEqual(signing.remove("app", "sideload", "default")[1], 409)
        self.assertEqual(signing.rotate("app", "default", "watch2")[1], 409)


class BackupPassword(unittest.TestCase):
    """A project's backup password (the operator, 1 Oct): set, changed only
    with the current one, needed for every download, held after five misses."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        signing.configure(state=self.tmp, project_name=re.compile(r"[A-Za-z0-9._-]+"))
        signing._tries.clear()

    def test_set_needed_changed_and_removed(self):
        self.assertIsNone(signing.backup_refusal("app", ""))
        self.assertEqual(signing.set_backup_password("app", "", "short")[1], 400)
        self.assertEqual(signing.set_backup_password("app", "", "a-long-password")[1], 200)
        self.assertNotIn("a-long-password", (self.tmp / "signing" / "app" / "backup-lock.json").read_text())
        self.assertEqual(signing.backup_refusal("app", "")[1], 403)
        self.assertEqual(signing.backup_refusal("app", "nope")[1], 403)
        self.assertIsNone(signing.backup_refusal("app", "a-long-password"))
        self.assertEqual(signing.set_backup_password("app", "wrong", "")[1], 403)
        self.assertEqual(signing.set_backup_password("app", "a-long-password", "")[0]["backup_locked"], False)
        self.assertIsNone(signing.backup_refusal("app", ""))

    def test_five_misses_hold_even_the_right_one(self):
        signing.set_backup_password("app", "", "a-long-password")
        for _ in range(5):
            signing.backup_refusal("app", "nope")
        self.assertEqual(signing.backup_refusal("app", "a-long-password")[1], 429)
