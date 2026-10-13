"""Copying or moving a container to another node, its data with it (the
operator, 10 Oct): the jobs each half runs, the data passed only to the jobs
that send and fetch it, a copy beside the original, a move that takes the
old node's containers down only once it is up, and the way back when one
fails."""
import io
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import devapp  # noqa: E402
import devactions  # noqa: E402
import paths  # noqa: E402
import relocate  # noqa: E402
from test_devapp_ship import Queue as ShipQueue, write_json  # noqa: E402


class Queue(ShipQueue):
    """...and what the rest of a compose action asks of it."""
    JOB_ACTIVE = ("queued", "running")

    def jobs_for(self, project="", type="", active=False, n=50, node_id=""):
        return [j for j in self.jobs.values()
                if (not active or j["state"] in self.JOB_ACTIVE)
                and (not project or j["spec"].get("project") == project)][:n]

    def jobs_state_rev(self):
        return 0


class Now:
    """threading.Thread, run at once: the plan is released before start()
    answers, so the test reads it."""

    def __init__(self, target, **_kw):
        self.target = target

    def start(self):
        self.target()


class Relocate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ws = Path(self.tmp) / "ws"
        (self.ws / "alpha").mkdir(parents=True)
        (self.ws / "alpha" / "docker-compose.yml").write_text("services:\n  web:\n    image: nginx\n")
        self.q = Queue()
        self.q.nodes["n3"] = {"id": "n3", "name": "nodec", "kind": "agent", "config": {}, "state": "online"}
        devapp.configure(workspace=self.ws, state=self.tmp, write_json=write_json, queue=self.q,
                         project_nodes=lambda p: ["n1", "n3"] if p == "alpha" else [],
                         project_node=lambda p: "n1" if p == "alpha" else "")
        devapp.all_project_nodes = lambda: {"alpha": ["n1", "n3"]}
        self.addCleanup(setattr, devapp, "all_project_nodes", None)
        paths.configure(state=self.tmp, workspace=self.ws)
        write_json(devapp.FILE, {"alpha": {"main": {"node": "n1", "risks_ack": "abc"}}})
        devapp.write_env("alpha", "PORT=1\n", "main")
        was = relocate.threading.Thread
        relocate.threading.Thread = Now
        self.addCleanup(setattr, relocate.threading, "Thread", was)
        self.acted = []
        real = devactions.act
        devactions.act = lambda p, i, a, req, **kw: (self.acted.append((p, i, a, req)) or ({"ok": True}, 200))
        self.addCleanup(setattr, devactions, "act", real)

    def jobs_on(self, node):
        return [j for j in self.q.jobs.values() if j["node"] == node]

    def end(self, jid, state="succeeded"):
        j = self.q.jobs[jid]
        j["state"] = state
        return devactions.compose_done(j, state)

    def test_a_copy_is_a_new_container_on_the_other_node_with_the_env_given(self):
        r = relocate.start("alpha", "main", "copy", "n2", "alpha-web", "PORT=2\n")
        self.assertTrue(r.get("ok"), r)
        new = devapp._read_rec("alpha", "alpha-web")
        self.assertEqual((new.get("node"), new.get("ship"), new.get("risks_ack")), ("n2", True, "abc"),
                         "n2 is not one of alpha's nodes, so its image is shipped; the yes to its risks goes with it")
        self.assertEqual(devapp.read_env("alpha", "alpha-web"), "PORT=2\n")
        self.assertEqual(devapp.read_env("alpha", "main"), "PORT=1\n", "the original's env is its own")
        out = self.q.jobs[r["job"]]
        self.assertEqual(out["node"], "n1")
        self.assertEqual([s["name"] for s in out["spec"]["plan"]], ["stopping", "packing", "sending", "starting"],
                         "stopped, packed, sent, and the original started again")
        self.assertEqual(out["spec"]["plan"][2]["to"], f"devdata-put?job={r['job']}")

    def test_a_move_leaves_the_old_one_stopped_and_keeps_its_name(self):
        r = relocate.start("alpha", "main", "move", "n3", "", "PORT=3\n")
        self.assertEqual(r.get("instance"), "main")
        names = [s["name"] for s in self.q.jobs[r["job"]]["spec"]["plan"]]
        self.assertEqual(names, ["stopping", "packing", "sending"], "a move does not start it again")
        self.assertEqual(devapp._read_rec("alpha", "main").get("node"), "n1", "still where it is until the data is over")

    def test_the_data_goes_only_to_the_jobs_moving_it(self):
        r = relocate.start("alpha", "main", "copy", "n2", "alpha-web")
        self.q.jobs[r["job"]]["state"] = "running"
        body = b"packed"
        self.assertEqual(relocate.data_put("n2", {"job": [r["job"]]}, io.BytesIO(body), 6)[1], 403, "not from another node")
        self.assertEqual(relocate.data_put("n1", {"job": [r["job"]]}, io.BytesIO(body), 6)[1], 200)
        self.end(r["job"])
        jin = next(j for j in self.jobs_on("n2"))
        self.assertEqual([s["name"] for s in jin["spec"]["plan"]], ["fetching", "unpacking"])
        self.assertIsNone(relocate.data_path("n2", {"job": [jin["id"]]})[0], "not before it is running")
        jin["state"] = "running"
        self.assertEqual(relocate.data_path("n1", {"job": [jin["id"]]})[1][1], 403, "not to another node")
        p, no = relocate.data_path("n2", {"job": [jin["id"]]})
        self.assertIsNone(no)
        self.assertEqual(p.read_bytes(), body)

    def test_the_data_may_come_in_pieces(self):
        """Through a tunnel's edge a request may carry at most 100 MB (R170): the
        agent sends offset and total, a piece that landed already is not
        taken twice, and the file is whole only when the last piece is."""
        r = relocate.start("alpha", "main", "copy", "n2", "alpha-web")
        self.q.jobs[r["job"]]["state"] = "running"
        q = lambda off, tot: {"job": [r["job"]], "offset": [str(off)], "total": [str(tot)]}  # noqa: E731
        self.assertEqual(relocate.data_put("n1", q(0, 6), io.BytesIO(b"abc"), 3), ({"ok": True, "bytes": 3, "more": True}, 200))
        self.assertEqual(relocate.data_put("n1", q(0, 6), io.BytesIO(b"abc"), 3)[0].get("again"), True, "a retry of a landed piece")
        self.assertEqual(relocate.data_put("n1", q(4, 6), io.BytesIO(b"x"), 1)[1], 409, "a hole is refused")
        self.assertEqual(relocate.data_put("n1", q(3, 6), io.BytesIO(b"def"), 3), ({"ok": True, "bytes": 6}, 200))
        self.assertEqual(relocate._data_file("alpha", "alpha-web").read_bytes(), b"abcdef")

    def test_a_move_switches_node_after_the_data_and_takes_the_old_down_once_up(self):
        r = relocate.start("alpha", "main", "move", "n3")
        self.q.jobs[r["job"]]["state"] = "running"
        relocate.data_put("n1", {"job": [r["job"]]}, io.BytesIO(b"x"), 1)
        self.end(r["job"])
        jin = next(j for j in self.jobs_on("n3"))
        self.end(jin["id"])
        rec = devapp._read_rec("alpha", "main")
        self.assertEqual((rec.get("node"), rec.get("ship")), ("n3", None), "n3 is alpha's own: built there, not shipped")
        self.assertEqual(self.acted, [("alpha", "main", "rebuild", {"ack": "abc"})])
        devactions.compose_done({"id": "jb", "node": "n3", "state": "succeeded",
                                 "spec": {"project": "alpha", "instance": "main", "action": "rebuild"}}, "succeeded")
        down = [j for j in self.jobs_on("n1") if j["spec"].get("action") == "down"]
        self.assertEqual(len(down), 1, "the old node's containers come down once the build lands")
        self.assertNotIn("relocating", devapp._read_rec("alpha", "main"))

    def test_a_move_that_does_not_come_up_goes_back_and_starts_there(self):
        r = relocate.start("alpha", "main", "move", "n3", "", "PORT=9\n")
        self.q.jobs[r["job"]]["state"] = "running"
        relocate.data_put("n1", {"job": [r["job"]]}, io.BytesIO(b"x"), 1)
        self.end(r["job"])
        self.end(next(j for j in self.jobs_on("n3"))["id"])
        devactions.compose_done({"id": "jb", "node": "n3", "state": "failed",
                                 "spec": {"project": "alpha", "instance": "main", "action": "rebuild"}}, "failed")
        rec = devapp._read_rec("alpha", "main")
        self.assertEqual(rec.get("node"), "n1", "back where it was")
        # Said in the bell, where it can be put away, not on the row for ever
        # (the operator, 11 Oct); gone once the container starts again.
        self.assertIsNone(relocate.view("alpha", "main"), "the row says nothing of it")
        rows = relocate.attention(lambda nid: nid)
        self.assertEqual([(r["kind"], r["id"], r["why"]) for r in rows],
                         [("relocate", "alpha|main", "it would not build on the new node")])
        self.assertGreater(rows[0]["at"], 0)
        devactions.compose_done({"id": "jc", "node": "n1", "state": "succeeded",
                                 "spec": {"project": "alpha", "instance": "main", "action": "up"}}, "succeeded")
        self.assertEqual(relocate.attention(lambda nid: nid), [], "built or started since: history")
        self.assertEqual(devapp.read_env("alpha", "main"), "PORT=1\n", "its env as it was")
        started = [j for j in self.jobs_on("n1") if j["spec"].get("action") == "start"]
        self.assertEqual(len(started), 1, "started again on the old node")

    def test_an_arriving_container_builds_and_stays_down(self):
        # The real plan (devactions._plan), with the record at the move's
        # last stage: build, down, and no up (R208, the operator, 13 Oct).
        import importlib
        real = importlib.import_module("devactions")
        rec = devapp._read_rec("alpha", "main")
        plain = [st["name"] for st in real._plan("alpha", "main", "rebuild")]
        self.assertEqual(plain, ["building", "stopping", "starting"], "a rebuild at home comes up")
        relocate._set("alpha", "main", relocating={"mode": "move", "to": "main", "old": "n1", "new": "n3", "stage": "build"})
        arriving = [st["name"] for st in real._plan("alpha", "main", "rebuild")]
        self.assertEqual(arriving, ["building", "stopping"], "on arrival it builds and stays down")
        relocate._set("alpha", "main", relocating=None)

    def test_a_copy_that_fails_to_pack_leaves_only_the_original(self):
        r = relocate.start("alpha", "main", "copy", "n2", "alpha-web")
        self.end(r["job"], "failed")
        self.assertNotIn("alpha-web", devapp._load().get("alpha", {}))
        self.assertIn("main", devapp._load().get("alpha", {}))
        self.assertFalse(devapp.env_path("alpha", "alpha-web").exists())

    def test_a_remove_on_a_quiet_node_queues_the_down_and_keeps_the_row(self):
        # B597: a node reads quiet for a minute every few (B550), and a remove
        # landing then forgot the row and left the container running.
        devapp._avail_hosts.clear()
        devapp._avail.update(val=None, when=0)
        r = devactions.remove_instance("alpha", "main")
        self.assertTrue(r.get("job"), r)
        self.assertEqual(self.q.jobs[r["job"]]["node"], "n1")
        self.assertIn("main", devapp._load().get("alpha", {}), "the row stays until the down has run")
        self.q.jobs[r["job"]]["state"] = "running"
        self.end(r["job"])
        self.assertNotIn("alpha", devapp._load(), "and goes once it has")

    def test_a_remove_on_a_retired_node_forgets_the_row(self):
        self.q.nodes["n1"]["state"] = "retired"
        devapp._avail_hosts.clear()
        devapp._avail.update(val=None, when=0)
        r = devactions.remove_instance("alpha", "main")
        self.assertTrue(r.get("forgot"), r)
        self.assertNotIn("alpha", devapp._load())

    def test_refusals(self):
        self.assertIn("already on", relocate.start("alpha", "main", "move", "n1")["error"])
        self.assertIn("name of its own", relocate.start("alpha", "main", "copy", "n2", "")["error"])
        self.q.nodes["n2"]["state"] = "offline"
        self.assertIn("not online", relocate.start("alpha", "main", "move", "n2")["error"])
        self.assertIn("no container", relocate.start("alpha", "nope", "move", "n3")["error"])


if __name__ == "__main__":
    unittest.main()
