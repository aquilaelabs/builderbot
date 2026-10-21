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
        # Running, unless a test says otherwise: what the old node does
        # around the data depends on it (B725).
        self.running = True
        was_running = devactions._running
        devactions._running = lambda p, i=devapp.MAIN: self.running
        self.addCleanup(setattr, devactions, "_running", was_running)

    def jobs_on(self, node):
        return [j for j in self.q.jobs.values() if j["node"] == node]

    def end(self, jid, state="succeeded"):
        j = self.q.jobs[jid]
        j["state"] = state
        return devactions.compose_done(j, state)

    def test_a_written_container_that_builds_an_image_ships_too(self):
        # A container written on the Docker tab for alpha, building an image
        # (B716): moved to n2, which is not alpha's, its image is built on
        # alpha's node and shipped, never built on n2, which holds no code.
        d = devapp._load()
        d["web"] = {"main": {"source": "file", "for": "alpha", "node": "n1"}}
        d["pulls"] = {"main": {"source": "file", "for": "alpha", "node": "n1"}}
        write_json(devapp.FILE, d)
        for name, text in (("web", "services:\n  app:\n    build: .\n"), ("pulls", "services:\n  db:\n    image: mariadb:11\n")):
            devapp.containers_dir(name).mkdir(parents=True, exist_ok=True)
            (devapp.containers_dir(name) / "docker-compose.yml").write_text(text)
        self.assertTrue(relocate.builds_image("web", "main"))
        self.assertFalse(relocate.builds_image("pulls", "main"))
        r = relocate.start("web", "main", "move", "n2")
        self.assertTrue(r.get("ok"), r)
        self.assertTrue(r.get("ship"), "a written container that builds ships, its image from alpha's node")
        r2 = relocate.start("pulls", "main", "move", "n2")
        self.assertTrue(r2.get("ok"), r2)
        self.assertFalse(r2.get("ship"), "one that only pulls images rebuilds where it lands")

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
        started = [j for j in self.jobs_on("n1") if j["spec"].get("action") == "up"]
        self.assertEqual(len(started), 1, "up again on the old node: up, which makes what a Down took away (B725)")

    def test_an_arriving_container_builds_and_stays_down(self):
        # The real plan (devactions._plan), with the record at the move's
        # last stage: build, down, and no up (R208, the operator, 13 Oct).
        import importlib
        real = importlib.import_module("devactions")
        plain = [st["name"] for st in real._plan("alpha", "main", "rebuild")]
        self.assertEqual(plain, ["building", "pulling", "stopping", "starting"], "a rebuild at home comes up")
        relocate._set("alpha", "main", relocating={"mode": "move", "to": "main", "old": "n1", "new": "n3", "stage": "build"})
        arriving = [st["name"] for st in real._plan("alpha", "main", "rebuild")]
        self.assertEqual(arriving, ["building", "pulling", "stopping"], "on arrival it builds and stays down")
        relocate._set("alpha", "main", relocating=None)

    def test_the_data_is_unpacked_on_arrival_unless_the_archive_is_to_stay(self):
        # The dialog's choice (the operator, 14 Oct): unpack at once, or
        # carry the archive and unpack from the row later.
        r = relocate.start("alpha", "main", "copy", "n3", "two")
        self.q.jobs[r["job"]]["state"] = "running"
        relocate.data_put("n1", {"job": [r["job"]]}, io.BytesIO(b"x"), 1)
        self.end(r["job"])
        jin = next(j for j in self.jobs_on("n3"))
        self.assertEqual([st["name"] for st in jin["spec"]["plan"]], ["fetching", "unpacking"])
        self.assertEqual(jin["spec"]["relocate"]["data"], "unpack")
        self.end(jin["id"])
        self.assertIsNone(devapp._read_rec("alpha", "two").get("archive"))

    def test_an_archive_stays_packed_and_the_row_unpacks_it_later(self):
        r = relocate.start("alpha", "main", "move", "n3", data="archive")
        self.q.jobs[r["job"]]["state"] = "running"
        relocate.data_put("n1", {"job": [r["job"]]}, io.BytesIO(b"x"), 1)
        self.end(r["job"])
        jin = next(j for j in self.jobs_on("n3"))
        self.assertEqual([st["name"] for st in jin["spec"]["plan"]], ["fetching"], "fetched, never unpacked")
        self.assertEqual(jin["spec"]["plan"][0]["dest"], relocate.ARCHIVE)
        self.assertEqual(relocate.view("alpha", "main")["line"], "moving to nodec: fetching its data")
        self.end(jin["id"])
        rec = devapp._read_rec("alpha", "main")
        self.assertEqual((rec.get("node"), rec.get("archive")), ("n3", True))
        self.assertEqual(self.acted, [("alpha", "main", "rebuild", {"ack": "abc"})], "built as any arrival is")
        devactions.compose_done({"id": "jb", "node": "n3", "state": "succeeded",
                                 "spec": {"project": "alpha", "instance": "main", "action": "rebuild"}}, "succeeded")
        v = relocate.view("alpha", "main")
        self.assertTrue(v["archive"] and not v["busy"] and "not unpacked" in v["line"] and "nodec" in v["line"], v)
        # The row's Unpack: one job on its node, stop, unpack, start (once
        # the old node's down, which this queue never runs, is over).
        for j in self.q.jobs.values():
            j["state"] = "succeeded"
        u = relocate.unpack_start("alpha", "main")
        self.assertTrue(u.get("ok"), u)
        ju = self.q.jobs[u["job"]]
        self.assertEqual(ju["node"], "n3")
        names = [st["name"] for st in ju["spec"]["plan"]]
        self.assertIn("unpacking", names)
        self.assertLess(names.index("stopping"), names.index("unpacking"))
        self.assertLess(names.index("unpacking"), names.index("starting"))
        self.assertEqual(ju["spec"]["plan"][names.index("unpacking")]["argv"][5], relocate.ARCHIVE)
        self.assertEqual(relocate.view("alpha", "main")["line"], "unpacking its data into its volumes on nodec")
        self.assertIn("being copied or moved", relocate.unpack_start("alpha", "main")["error"])
        self.end(ju["id"])
        rec = devapp._read_rec("alpha", "main")
        self.assertNotIn("archive", rec)
        self.assertNotIn("relocating", rec)
        self.assertIsNone(relocate.view("alpha", "main"))
        self.assertIn("not waiting in an archive", relocate.unpack_start("alpha", "main")["error"])

    def test_an_unpack_that_fails_keeps_the_archive_and_says_so(self):
        relocate._set("alpha", "main", archive=True)
        u = relocate.unpack_start("alpha", "main")
        said = self.end(u["job"], "failed")
        self.assertIn("unpacking its data failed", said)
        rec = devapp._read_rec("alpha", "main")
        self.assertEqual(rec.get("archive"), True, "still there to try again")
        self.assertNotIn("relocating", rec)
        self.assertEqual([r["why"] for r in relocate.attention(lambda nid: nid)], [said])
        self.assertTrue(relocate.view("alpha", "main")["archive"], "the row still offers it")

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

    def test_the_data_word_is_one_of_three(self):
        self.assertIn("unpack, archive or none", relocate.start("alpha", "main", "move", "n3", data="x")["error"])
        self.assertTrue(relocate.start("alpha", "main", "move", "n3", data="")["ok"], "nothing said is unpack")

    def test_one_that_is_down_is_neither_stopped_nor_started_around_the_data(self):
        # B725: start on no containers exited 1, failing a copy after its
        # data was sent, and leaving a failed move down at home.
        self.running = False
        r = relocate.start("alpha", "main", "copy", "n3", "two")
        out = self.q.jobs[r["job"]]
        self.assertEqual([st["name"] for st in out["spec"]["plan"]], ["packing", "sending"], "left as it is")
        self.assertFalse(out["spec"]["relocate"]["was_up"])
        relocate._drop("alpha", "two")
        self.q.jobs.clear()
        r = relocate.start("alpha", "main", "move", "n3")
        self.assertEqual([st["name"] for st in self.q.jobs[r["job"]]["spec"]["plan"]], ["packing", "sending"])
        self.q.jobs[r["job"]]["state"] = "running"
        relocate.data_put("n1", {"job": [r["job"]]}, io.BytesIO(b"x"), 1)
        self.end(r["job"])
        self.end(next(j for j in self.jobs_on("n3"))["id"], "failed")
        self.assertEqual(devapp._read_rec("alpha", "main").get("node"), "n1", "back where it was")
        self.assertEqual([j["spec"].get("action") for j in self.jobs_on("n1") if j["spec"].get("action") in ("up", "start")], [],
                         "it was down, so it stays down")

    def test_no_data_sends_the_container_alone(self):
        # The third choice (the operator, 14 Oct): a copy is the record and
        # a build on the new node, nothing on the old; a running move stops
        # here first, a down one does not even that.
        r = relocate.start("alpha", "main", "copy", "n3", "two", data="none")
        self.assertTrue(r["ok"] and r["job"] == "", r)
        self.assertEqual(self.jobs_on("n1"), [], "nothing packed or stopped")
        self.assertEqual(self.acted, [("alpha", "two", "rebuild", {"ack": "abc"})])
        self.assertEqual(devapp._read_rec("alpha", "two")["relocating"]["stage"], "build")
        self.acted.clear()
        r = relocate.start("alpha", "main", "move", "n3", data="none")
        out = self.q.jobs[r["job"]]
        self.assertEqual([st["name"] for st in out["spec"]["plan"]], ["stopping"])
        self.assertEqual(relocate.view("alpha", "main")["line"], "moving to nodec: stopping it")
        self.end(r["job"])
        self.assertEqual(self.jobs_on("n3"), [], "no in job: nothing to fetch")
        rec = devapp._read_rec("alpha", "main")
        self.assertEqual((rec.get("node"), rec["relocating"]["stage"]), ("n3", "build"))
        self.assertEqual(self.acted, [("alpha", "main", "rebuild", {"ack": "abc"})])
        relocate._set("alpha", "main", relocating=None, node="n1")
        self.running = False
        r = relocate.start("alpha", "main", "move", "n3", data="none")
        self.assertEqual(r["job"], "", "down already: its record moves and it builds there, no job at home")
        self.assertEqual(devapp._read_rec("alpha", "main").get("node"), "n3")

    def test_refusals(self):
        self.assertIn("already on", relocate.start("alpha", "main", "move", "n1")["error"])
        self.assertIn("name of its own", relocate.start("alpha", "main", "copy", "n2", "")["error"])
        self.q.nodes["n2"]["state"] = "offline"
        self.assertIn("not online", relocate.start("alpha", "main", "move", "n2")["error"])
        self.assertIn("no container", relocate.start("alpha", "nope", "move", "n3")["error"])


if __name__ == "__main__":
    unittest.main()


class UnpackTrustsNoManifest(unittest.TestCase):
    """The unpack script runs on the new node over an archive the old node
    packed, and a hosting-only box that was taken over writes that archive:
    it writes the moved instance's own volumes and no other (R92)."""

    def run_unpack(self, manifest, have=(), labels=None):
        import json
        import subprocess
        import tarfile
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        calls = d / "calls"
        labels = labels or {}
        (d / "bin").mkdir()
        # A docker that lists `have`, answers each volume's compose label
        # from `labels`, and logs every other call.
        (d / "bin" / "docker").write_text(
            "#!/bin/sh\n"
            f"echo \"$*\" >> {calls}\n"
            "case \"$1 $2\" in\n"
            f"  'volume ls') printf '%s\\n' {' '.join(have) or ''} ;;\n"
            "  'volume inspect') case \"$5\" in\n"
            + "".join(f"    {k}) echo {v} ;;\n" for k, v in labels.items())
            + "  esac ;;\n"
            "esac\n")
        (d / "bin" / "docker").chmod(0o755)
        (d / "manifest.json").write_text(json.dumps(manifest))
        src = d / "data.tar"
        with tarfile.open(src, "w") as t:
            t.add(d / "manifest.json", arcname="manifest.json")
        r = subprocess.run([sys.executable, "-c", relocate.UNPACK_PY, "web", "old", str(src), "", "busybox"],
                           capture_output=True, text=True,
                           env={**os.environ, "PATH": f"{d / 'bin'}:{os.environ['PATH']}"})
        return r, (calls.read_text() if calls.exists() else "")

    def test_its_own_volume_is_filled(self):
        r, calls = self.run_unpack({"volumes": [{"name": "old_db", "part": "vol-0.tgz"}]})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("volume create", calls)
        self.assertIn("web_db:/v", calls)

    def test_another_projects_volume_is_not_written_over(self):
        r, calls = self.run_unpack({"volumes": [{"name": "nextcloud_html", "part": "vol-0.tgz"}]},
                                   have=["nextcloud_html"], labels={"nextcloud_html": "nextcloud"})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not this instance's", r.stderr)
        self.assertNotIn("nextcloud_html:/v", calls)

    def test_a_name_or_part_it_could_not_have_packed_is_refused(self):
        for v in ({"name": "../etc", "part": "vol-0.tgz"}, {"name": "old_db", "part": "../../x"},
                  {"name": "old_db", "part": "data.tgz"}):
            r, calls = self.run_unpack({"volumes": [v]})
            self.assertNotEqual(r.returncode, 0, v)
            self.assertNotIn(":/v", calls, v)
