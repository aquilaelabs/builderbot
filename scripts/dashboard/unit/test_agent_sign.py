"""The node agent's sign job (R106 step 2), with the store's real jarsigner
where one is installed: an .aab signed with the kept key and delivered as
NAME-signed, the work directory gone after, and the refusals: a node whose
jobs and sessions share an account, and a key handed over that is not the
one the controller says it kept."""
import base64
import glob
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
import agentpkg  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
agent = agentpkg.load("builderbot_agent_sign")
agent.log = lambda *a, **k: None

STORE = next((d for d in glob.glob("/mnt/SDK/*") + glob.glob("/sdk/*")
              if os.access(os.path.join(d, "jdk", "bin", "jarsigner"), os.X_OK)), "")


class Ctl:
    def __init__(self, src, key):
        self.src, self.key, self.got = src, key, None

    def fetch(self, path, dest, timeout=600):
        shutil.copyfile(self.src, dest)
        return 200, {}

    def call(self, verb, body=None, timeout=30):
        return 200, self.key

    def upload(self, path, src, timeout=600):
        self.path = path
        self.got = path.split("name=")[1].split("&")[0]
        return 200, {"path": "dist/" + self.got, "size": os.path.getsize(src), "sha256": "x"}


class Job:
    def __init__(self):
        self.job, self.outputs, self.lines = {"id": "j_unit"}, [], []

    def say(self, t):
        self.lines.append(t)


class Sign(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.was = agent.os.geteuid
        self.addCleanup(setattr, agent.os, "geteuid", self.was)
        agent.os.geteuid = lambda: 0
        self.addCleanup(setattr, agent, "tc_root", agent.tc_root)
        agent.tc_root = lambda st: STORE
        self.addCleanup(setattr, agent, "SIGN_WORK", agent.SIGN_WORK)
        agent.SIGN_WORK = os.path.join(self.tmp, "signwork")

    def agent_with(self, src, key, user="builder", sessions="sessions"):
        a = object.__new__(agent.Agent)
        a.state = {"user": user, "stores": {"data": os.path.join(self.tmp, "data")}}
        a.session_account = lambda: sessions
        a.drop_privileges = lambda env: {}
        a.ctl = Ctl(src, key)
        return a

    def test_a_shared_account_is_refused_before_anything_is_fetched(self):
        a = self.agent_with("", {}, user="builder", sessions="builder")
        j = Job()
        self.assertEqual(a.sign(j, {"route": "play", "file": "app.aab"}), ("failed", 77))
        self.assertIn("one account", "".join(j.lines))

    @unittest.skipUnless(STORE, "no jdk in a toolchain store here")
    def test_an_aab_is_signed_verified_and_the_work_removed(self):
        kt = os.path.join(STORE, "jdk", "bin", "keytool")
        ks = os.path.join(self.tmp, "k.p12")
        subprocess.run([kt, "-genkeypair", "-keystore", ks, "-storetype", "PKCS12", "-storepass", "pw123456",
                        "-alias", "upload", "-keyalg", "RSA", "-keysize", "2048", "-validity", "100",
                        "-dname", "CN=T"], check=True, capture_output=True)
        out = subprocess.run([kt, "-list", "-v", "-keystore", ks, "-storepass", "pw123456"],
                             check=True, capture_output=True, text=True).stdout
        sha = out.split("SHA256:")[1].split()[0]
        aab = os.path.join(self.tmp, "app-release-unsigned.aab")
        with zipfile.ZipFile(aab, "w") as z:
            z.writestr("base/manifest/AndroidManifest.xml", "x")
        with open(ks, "rb") as h:
            raw = h.read()
        key = {"keystore": base64.b64encode(raw).decode(), "alias": "upload",
               "store_pass": "pw123456", "key_pass": "pw123456", "sha256": sha}
        a, j = self.agent_with(aab, key), Job()
        self.assertEqual(a.sign(j, {"route": "play", "file": "app-release-unsigned.aab"}), ("succeeded", 0),
                         "".join(j.lines))
        self.assertEqual(a.ctl.got, "app-release-signed.aab")
        # ...and its upload says what signed it, for the Artifacts row.
        self.assertIn("&signed=play&cert=", a.ctl.path)
        self.assertTrue(a.ctl.path.endswith("&schemes=jar&key=default"), a.ctl.path)
        self.assertEqual(j.outputs[0]["signed"], "play")
        self.assertEqual(os.listdir(os.path.join(self.tmp, "signwork", "build")), [])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "data", "sign")), "never on the data store (B315)")
        self.assertNotIn("pw123456", "".join(j.lines))


class KeyCtl:
    """The channel as a sign-key job sees it: what it is handed, and what it
    answers, kept."""

    def __init__(self, give):
        self.give, self.said = give, []

    def call(self, verb, body=None, timeout=30):
        if verb == "signing-key":
            return 200, self.give
        self.said.append((verb, body))
        return 200, {"ok": True}


class SignKey(unittest.TestCase):
    """The controller's key work on this node (R106, the operator 22 Oct):
    refused where a session could read the key, the missing toolchain named
    back to the controller, and a keystore checked and a key made with the
    store's keytool, the answer sent over the channel, nothing of the
    password in the job's log and the work directory gone."""

    setUp = Sign.setUp

    def agent_with(self, give, user="builder", sessions="sessions"):
        a = Sign.agent_with(self, "", {}, user=user, sessions=sessions)
        a.ctl = KeyCtl(give)
        return a

    def test_a_shared_account_is_refused_and_says_why(self):
        a, j = self.agent_with({}, sessions="builder"), Job()
        self.assertEqual(a.sign_key(j, {"op": "inspect"}), ("failed", 77))
        self.assertIn("one account", a.ctl.said[0][1]["error"])

    def test_a_node_with_no_jdk_says_so(self):
        agent.tc_root = lambda st: self.tmp
        a, j = self.agent_with({}), Job()
        self.assertEqual(a.sign_key(j, {"op": "generate"}), ("failed", 69))
        self.assertEqual(a.ctl.said, [("signing-result", {"job": "j_unit", "missing": "jdk"})])

    @unittest.skipUnless(STORE, "no jdk in a toolchain store here")
    def test_a_key_made_and_checked_here(self):
        a, j = self.agent_with({"alias": "watch", "cn": "Watch", "password": "pw-made-here"}), Job()
        self.assertEqual(a.sign_key(j, {"op": "generate"}), ("succeeded", 0), "".join(j.lines))
        verb, made = a.ctl.said[0]
        self.assertEqual((verb, made["alias"]), ("signing-result", "watch"))
        self.assertRegex(made["sha256"], r"^([0-9A-F]{2}:){31}[0-9A-F]{2}$")
        a2, j2 = self.agent_with({"keystore": made["keystore"], "store_pass": "pw-made-here"}), Job()
        self.assertEqual(a2.sign_key(j2, {"op": "inspect"}), ("succeeded", 0))
        self.assertEqual(a2.ctl.said[0][1]["sha256"], made["sha256"])
        a3, j3 = self.agent_with({"keystore": made["keystore"], "store_pass": "wrong"}), Job()
        self.assertEqual(a3.sign_key(j3, {"op": "inspect"}), ("failed", 1))
        self.assertEqual(a3.ctl.said[0][1]["error"], "the keystore's password is not that")
        self.assertNotIn("pw-made-here", "".join(j.lines + j2.lines + j3.lines))
        self.assertEqual(os.listdir(os.path.join(self.tmp, "signwork", "key")), [])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "data", "sign-key")), "never on the data store (B315)")


if __name__ == "__main__":
    unittest.main()
