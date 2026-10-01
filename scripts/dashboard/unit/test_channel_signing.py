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
        self.was = (channel.nodes.job, channel.signing.secret, channel.db.audit)
        channel.nodes.job = lambda jid, with_log=True: self.jobs.get(jid)
        channel.signing.secret = lambda p, r: (b"KEY", {"alias": "upload", "store_pass": "pw", "sha256": "AB"})
        channel.db.audit = lambda *a: self.audit.append(a)
        channel._keys_given.clear()

    def tearDown(self):
        channel.nodes.job, channel.signing.secret, channel.db.audit = self.was

    def ask(self, job, node="n_1"):
        return channel.verb("signing-key", {"kind": "node", "node": node, "principal": "node:" + node},
                            {"job": job}, "10.0.0.1")

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
