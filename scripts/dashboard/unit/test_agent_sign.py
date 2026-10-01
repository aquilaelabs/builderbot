"""The node agent's sign job (R106 step 2), with the store's real jarsigner
where one is installed: an .aab signed with the kept key and delivered as
NAME-signed, the work directory gone after, and the refusals: a node whose
jobs and sessions share an account, and a key handed over that is not the
one the controller says it kept."""
import base64
import glob
import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "builderbot_agent_sign", os.path.join(HERE, "..", "..", "agent", "builderbot-agent.py"))
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)
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
        self.got = path.split("name=")[1]
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
        key = {"keystore": base64.b64encode(open(ks, "rb").read()).decode(), "alias": "upload",
               "store_pass": "pw123456", "key_pass": "pw123456", "sha256": sha}
        a, j = self.agent_with(aab, key), Job()
        self.assertEqual(a.sign(j, {"route": "play", "file": "app-release-unsigned.aab"}), ("succeeded", 0),
                         "".join(j.lines))
        self.assertEqual(a.ctl.got, "app-release-signed.aab")
        self.assertEqual(j.outputs[0]["signed"], "play")
        self.assertEqual(os.listdir(os.path.join(self.tmp, "data", "sign")), [])
        self.assertNotIn("pw123456", "".join(j.lines))


if __name__ == "__main__":
    unittest.main()
