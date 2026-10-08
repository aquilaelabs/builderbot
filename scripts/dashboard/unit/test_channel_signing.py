"""The agent channel's signing-key verb (R106 step 2): a key goes only to
the running sign job's own node, once, and is audited."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import channel  # noqa: E402


class SigningKey(unittest.TestCase):
    def setUp(self):
        self.jobs = {"j_1": {"id": "j_1", "type": "sign", "node": "n_1", "state": "running",
                             "project": "app", "spec": {"route": "play"}},
                     "j_2": {"id": "j_2", "type": "exec", "node": "n_1", "state": "running",
                             "project": "app", "spec": {"route": "play"}}}
        self.audit = []
        self.was = (channel.nodes.job, channel.signing.secret, channel.db.audit, channel.signing.key_for)
        channel.nodes.job = lambda jid, with_log=True: self.jobs.get(jid)
        self.asked = []
        channel.signing.secret = lambda p, r, k="default": (self.asked.append(k) or (b"KEY", {"alias": "upload", "store_pass": "pw", "sha256": "AB"}))
        channel.signing.key_for = lambda p, pkg, route="": "watch" if pkg == "com.example.watch" else "default"
        channel.db.audit = lambda *a: self.audit.append(a)
        channel._keys_given.clear()

    def tearDown(self):
        channel.nodes.job, channel.signing.secret, channel.db.audit, channel.signing.key_for = self.was

    def ask(self, job, node="n_1", package=""):
        return channel.verb("signing-key", {"kind": "node", "node": node, "principal": "node:" + node},
                            {"job": job, "package": package}, "10.0.0.1")

    def test_the_package_picks_the_key_unless_the_job_names_one(self):
        r, st = self.ask("j_1", package="com.example.watch")
        self.assertEqual((st, r["key"], self.asked[-1]), (200, "watch", "watch"))
        channel._keys_given.clear()
        self.jobs["j_1"]["spec"]["key"] = "phone"
        self.assertEqual(self.ask("j_1", package="com.example.watch")[0]["key"], "phone")

    def test_once_to_the_jobs_own_node(self):
        r, st = self.ask("j_1")
        self.assertEqual(st, 200)
        self.assertEqual(r["alias"], "upload")
        self.assertEqual(len(self.audit), 1)
        self.assertEqual(self.ask("j_1")[1], 409)

    def test_another_node_or_another_kind_of_job_gets_nothing(self):
        self.assertEqual(self.ask("j_1", node="n_2")[1], 403)
        self.assertEqual(self.ask("j_2")[1], 403)
        self.jobs["j_1"]["state"] = "succeeded"
        self.assertEqual(self.ask("j_1")[1], 403)
        self.assertEqual(self.audit, [])


if __name__ == "__main__":
    unittest.main()


class SignedArtifact(unittest.TestCase):
    """A sign job's upload says what signed it (step 4), in the shape it can
    have; any other job's says nothing of the kind."""

    def setUp(self):
        self.put = []
        self.was = (channel.nodes.job, channel.workspace.artifact_put, channel.db.audit)
        self.jobs = {"j_s": {"id": "j_s", "type": "sign", "node": "n_1", "state": "running",
                             "project": "app", "spec": {"route": "sideload", "file": "app.apk"}},
                     "j_e": {"id": "j_e", "type": "exec", "node": "n_1", "state": "running",
                             "project": "app", "spec": {}}}
        channel.nodes.job = lambda jid, with_log=True: self.jobs.get(jid)
        channel.workspace.artifact_put = lambda j, name, stream, length, extra=None: (
            self.put.append(extra) or {"path": "dist/" + name, "sha256": "x"})
        channel.db.audit = lambda *a: None

    def tearDown(self):
        channel.nodes.job, channel.workspace.artifact_put, channel.db.audit = self.was

    def send(self, job, **q):
        query = {"job": [job], "name": ["app-signed.apk"]} | {k: [v] for k, v in q.items()}
        return channel.artifact({"kind": "node", "node": "n_1", "principal": "node:n_1"}, query, None, 1)

    def test_a_sign_jobs_upload_says_what_signed_it(self):
        self.send("j_s", signed="sideload", cert="ab" * 32, schemes="v2,v3")
        self.assertEqual(self.put[-1], {"signed": {"route": "sideload", "cert": "AB" * 32, "key": "default",
                                                   "schemes": ["v2", "v3"], "from": "app.apk"}})

    def test_nothing_else_is_taken_for_it(self):
        self.send("j_e", signed="sideload", cert="ab" * 32, schemes="v2")
        self.send("j_s", signed="sideload", cert="not-a-digest", schemes="v2")
        self.assertEqual(self.put, [{}, {}])
