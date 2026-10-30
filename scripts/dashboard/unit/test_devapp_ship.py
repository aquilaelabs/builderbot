"""A dev instance sent to a node its project is not on (R166): made only on
purpose, its image built on the project's own node and shipped, the two
jobs' plans, the image passed only to the jobs that ship and load it, binds
into the project's tree refused, and the project's sessions reaching it."""
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import devapp  # noqa: E402
import devactions  # noqa: E402
import paths  # noqa: E402


def write_json(p, d, mode=0o644):
    Path(p).write_text(json.dumps(d))


class Queue:
    """The job queue, as far as shipping asks of it."""

    def __init__(self):
        self.jobs, self.n = {}, 0
        self.nodes = {"n1": {"id": "n1", "name": "nodea", "kind": "agent", "config": {}, "state": "online"},
                      "n2": {"id": "n2", "name": "nodeb", "kind": "agent", "config": {}, "state": "online",
                             "agent": {"addr": "10.0.0.2"},
                             "reported": {"sandbox": True, "published": {"web": [8080]}}}}

    def node(self, nid):
        return self.nodes.get(nid)

    def first_up(self, nids):
        return (nids[0] if nids else ""), ""

    def job_add(self, who, placement, kind, spec, project=""):
        self.n += 1
        jid = f"j_{self.n}"
        self.jobs[jid] = {"id": jid, "node": placement["node"], "state": "queued", "spec": dict(spec)}
        return {"ok": True, "job": jid}

    def job_release(self, jid, spec):
        self.jobs[jid]["spec"] = spec
        return True

    def job_refuse(self, jid, why):
        self.jobs[jid].update(state="failed", error=why)

    def job(self, jid, with_log=True):
        return self.jobs.get(jid)

    def job_tail(self, jid, n):
        return ""


class Ship(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ws = Path(self.tmp) / "ws"
        (self.ws / "alpha").mkdir(parents=True)
        (self.ws / "alpha" / "docker-compose.yml").write_text("services:\n  web:\n    build: .\n")
        self.q = Queue()
        devapp.configure(workspace=self.ws, state=self.tmp, write_json=write_json, queue=self.q,
                         project_nodes=lambda p: ["n1"] if p == "alpha" else [],
                         project_node=lambda p: "n1" if p == "alpha" else "")
        devapp.all_project_nodes = lambda: {"alpha": ["n1"]}
        self.addCleanup(setattr, devapp, "all_project_nodes", None)
        paths.configure(state=self.tmp, workspace=self.ws)
        write_json(devapp.FILE, {})

    def make(self, node="n2", ship=True):
        return devapp.create_instance("alpha", "web", node, ship=ship)

    def test_a_written_container_builds_on_its_owners_node(self):
        # The written container's owner is alpha, whose node is n1: the
        # shipped build runs there, against its data directory, not against
        # a tree the container does not have (B716).
        write_json(devapp.FILE, {"web": {"main": {"source": "file", "for": "alpha", "node": "n2", "ship": True}}})
        devapp.containers_dir("web").mkdir(parents=True, exist_ok=True)
        (devapp.containers_dir("web") / "docker-compose.yml").write_text("services:\n  app:\n    build: .\n")
        r = devactions._ship_submit("web", "main", "n2")
        # Its prepare thread is waited for here: left running, it released
        # j_1 into the next test's queue, which never held it (B438).
        for t in threading.enumerate():
            if t.name == f"prepare-{r.get('job')}":
                t.join(10)
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(self.q.jobs[r["job"]]["node"], "n1", "built on the owner's node, not the container's own name's")
        b = devactions._ship_build_spec("web", "main", "j_9")
        argv = " ".join(b["plan"][0]["argv"])
        self.assertNotIn(str(self.ws / "web"), argv, "no tree of its own is named as the project directory")
        self.assertIn("web", argv[argv.index("--project-directory"):], "its own data directory is")

    def test_only_on_purpose(self):
        r = self.make(ship=False)
        self.assertIn("out of reach of its sessions", r.get("error", ""), "a node outside the set, not asked to ship")
        r = self.make()
        self.assertTrue(r.get("ok"), r)
        rec = devapp._read_rec("alpha", r["instance"])
        self.assertEqual((rec.get("node"), rec.get("ship")), ("n2", True))
        self.assertTrue(devactions.shipped("alpha", r["instance"]))
        own = devapp.create_instance("alpha", "own", "n1", ship=True)
        self.assertFalse(devapp._read_rec("alpha", own["instance"]).get("ship"),
                         "one of the project's own nodes builds there, and ships nothing")

    def test_the_two_plans(self):
        inst = self.make()["instance"]
        b = devactions._ship_build_spec("alpha", inst, "j_9")
        names = [s["name"] for s in b["plan"]]
        self.assertEqual(names, ["building", "saving", "shipping"])
        self.assertIn(str(self.ws / "alpha"), b["plan"][0]["argv"], "built from the build node's own copy")
        self.assertEqual(b["plan"][2], {"name": "shipping", "upload": "{cdir}/image.tar",
                                        "to": "devimage-put?job=j_9", "timeout": 3600})
        self.assertEqual(b["ship"], "build")
        r = devactions._ship_run_spec("alpha", inst, "j_10")
        names = [s["name"] for s in r["plan"]]
        self.assertEqual(names[:3], ["fetching", "loading", "loading"])
        self.assertNotIn("building", names, "nothing is built on the instance's node")
        up = next(s for s in r["plan"] if s["name"] == "starting")["argv"]
        self.assertIn("--no-build", up)
        self.assertEqual(up[up.index("--pull") + 1], "missing", "what the tar did not carry is pulled (B660)")
        self.assertIn("{cdir}", up, "run from its own compose directory, not a tree it does not have")
        self.assertNotIn(str(self.ws / "alpha"), " ".join(up))

    def test_the_image_goes_only_to_the_jobs_shipping_it(self):
        inst = self.make()["instance"]
        self.q.jobs["j_1"] = {"id": "j_1", "node": "n1", "state": "running",
                              "spec": {"project": "alpha", "instance": inst, "ship": "build"}}
        self.q.jobs["j_2"] = {"id": "j_2", "node": "n2", "state": "running",
                              "spec": {"project": "alpha", "instance": inst, "ship": "run"}}
        body = b"image bytes"
        self.assertEqual(devactions.image_put("n2", {"job": ["j_1"]}, io.BytesIO(body), len(body))[1], 403,
                         "not from another node")
        self.assertEqual(devactions.image_put("n1", {"job": ["j_2"]}, io.BytesIO(body), len(body))[1], 403,
                         "not for a job that is loading")
        out, code = devactions.image_put("n1", {"job": ["j_1"]}, io.BytesIO(body), len(body))
        self.assertEqual(code, 200, out)
        self.assertIsNotNone(devactions.image_path("n1", {"job": ["j_1"]})[1], "the build node does not fetch it")
        p, no = devactions.image_path("n2", {"job": ["j_2"]})
        self.assertIsNone(no)
        self.assertEqual(p.read_bytes(), body)
        self.assertTrue(str(p).startswith(str(paths.of("images"))))
        # Handed over and not yet marked running: the fetch is the run half's
        # first step and can reach here before the agent's first log post
        # (B648), so an assigned job is served too.
        self.q.jobs["j_2"]["state"] = "assigned"
        self.assertIsNone(devactions.image_path("n2", {"job": ["j_2"]})[1], "an assigned job fetches it")
        self.q.jobs["j_2"]["state"] = "succeeded"
        self.assertIsNotNone(devactions.image_path("n2", {"job": ["j_2"]})[1], "nor once its job has ended")

    def test_binds_into_the_tree_are_refused(self):
        cfg = {"services": {"web": {"volumes": [
            {"type": "bind", "source": str(self.ws / "alpha" / "src"), "target": "/app"},
            {"type": "bind", "source": "/srv/data", "target": "/data"},
            {"type": "volume", "source": "db", "target": "/db"}]}}}
        bad = devactions.ship_binds("alpha", cfg)
        self.assertEqual(bad, [f"web mounts {self.ws / 'alpha' / 'src'}"])

    def test_its_sessions_reach_it_on_the_other_node(self):
        self.make()
        own = devapp.session_net_own("n1")
        self.assertIn(("10.0.0.2", 8080), [tuple(x) for x in own["alpha"]["peers"]],
                      "a session on the project's node reaches the shipped container's published port")

    def test_a_hosting_only_node_is_never_opened_whole(self):
        # It says it is no sandbox, which would open its whole address: a
        # public box's word about itself is not taken (R92).
        n2 = self.q.nodes["n2"]
        n2["reported"]["sandbox"], n2["config"]["host_only"] = False, True
        self.make()
        own = devapp.session_net_own("n1")
        self.assertNotIn("10.0.0.2", own["alpha"]["hosts"])
        self.assertIn(("10.0.0.2", 8080), [tuple(x) for x in own["alpha"]["peers"]])


if __name__ == "__main__":
    unittest.main()
