"""phonelease.py (R113): a phone lent to a project. Lending is its owner's and
only to a project on the phone's node; a lease ends by itself; a session
drives only the lease's own apps, and touches the screen only while one of
them is in front or is the keyboard. adb is faked: what is checked is what
would be sent to the phone, and what is refused before anything is."""
import base64
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import phone  # noqa: E402
import phonelease as pl  # noqa: E402

OWNER = {"uid": "u1", "name": "Owner"}
OTHER = {"uid": "u2", "name": "Other"}


class Users:
    @staticmethod
    def uid_of(who):
        return (who or {}).get("uid", "")


class Lease(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.recs = {"n1": {"owner": "u1", "serial": "10.0.0.5:4000"}}
        self.sent = []
        self.answer = {"code": 0, "out": "ok"}
        saved = {k: getattr(phone, k) for k in ("_rec", "_put", "_adb", "phone_on", "users", "load")}
        self.addCleanup(lambda: [setattr(phone, k, v) for k, v in saved.items()])
        phone._rec = lambda nid: self.recs.get(nid)
        phone._put = lambda nid, rec: self.recs.__setitem__(nid, rec) if rec else self.recs.pop(nid, None)
        phone.phone_on = lambda nid, **kw: {"serial": "10.0.0.5:4000", "model": "Pixel"} if nid in self.recs else None
        phone.users = Users

        def adb(nid, *args, **kw):
            self.sent.append(args)
            return dict(self.answer)
        phone._adb = adb
        phone.load = lambda: {"nodes": self.recs}
        pl.configure(workspace=self.tmp, project_node_fn=lambda p: {"app": "n1", "far": "n2"}.get(p, ""),
                     may_see_fn=lambda who, p: p in ("app", "far"))

    def test_only_the_owner_lends_and_only_to_a_project_on_the_node(self):
        self.assertIn("error", pl.lend("n1", OTHER, "app", 1))
        self.assertIn("another node", pl.lend("n1", OWNER, "far", 1)["error"])
        self.assertIn("error", pl.lend("n1", OWNER, "app", 3))
        self.assertTrue(pl.lend("n1", OWNER, "app", 1)["ok"])
        self.assertEqual(pl.leased_to("app")[1]["project"], "app")
        self.assertIn("error", pl.take_back("n1", OTHER))
        self.assertTrue(pl.take_back("n1", OTHER, admin=True)["ok"])
        self.assertIsNone(pl.leased_to("app")[1])

    def test_a_lease_ends_by_itself(self):
        pl.lend("n1", OWNER, "app", 1)
        self.recs["n1"]["lease"]["until"] = int(time.time()) - 1
        self.assertIsNone(pl.lease("n1"))
        self.assertNotIn("lease", self.recs["n1"])
        pl.lend("n1", OWNER, "app", 0)
        self.assertEqual(self.recs["n1"]["lease"]["until"], 0)
        self.assertIsNotNone(pl.lease("n1"))

    def test_nothing_without_a_lease_and_only_the_lease_apps_with_one(self):
        r, st = pl.use("app", "shot", {})
        self.assertEqual(st, 403)
        pl.lend("n1", OWNER, "app", 1)
        r, st = pl.use("app", "start", {"pkg": "com.other.app"})
        self.assertEqual(st, 403)
        self.assertEqual(self.sent, [])
        pl._add_pkg("n1", "dev.shebang.devboard")
        r, st = pl.use("app", "start", {"pkg": "dev.shebang.devboard"})
        self.assertEqual(st, 200)
        self.assertIn("monkey -p dev.shebang.devboard", self.sent[-1][-1])

    def test_a_touch_is_guarded_and_built_from_numbers(self):
        pl.lend("n1", OWNER, "app", 1)
        pl._add_pkg("n1", "dev.app")
        r, st = pl.use("app", "touch", {"kind": "tap", "x": "10", "y": "20"})
        line = self.sent[-1][-1]
        self.assertIn("*dev.app/*", line)
        self.assertTrue(line.endswith("input tap 10 20"))
        self.assertEqual(pl.use("app", "touch", {"kind": "tap", "x": "10; reboot", "y": "1"})[1], 400)
        self.assertEqual(pl.use("app", "touch", {"kind": "key", "key": "home"})[1], 400)
        pl.use("app", "touch", {"kind": "text", "text": "a b'; reboot"})
        # Spaces become input's %s, and the whole is one quoted word for the
        # phone's shell, so nothing typed can end the command.
        self.assertTrue(self.sent[-1][-1].endswith("input text 'a%sb'\"'\"';%sreboot'"))
        pl.use("app", "touch", {"kind": "glide", "points": [1, 2, 3, 4, 5, 6], "ms": 30})
        g = self.sent[-1][-1]
        self.assertIn("input motionevent DOWN 1 2", g)
        self.assertIn("sleep 0.030", g)
        self.assertTrue(g.endswith("input motionevent UP 5 6"))
        self.answer = {"code": 3, "out": "bb-not-yours: com.android.settings"}
        self.assertEqual(pl.use("app", "touch", {"kind": "tap", "x": 1, "y": 1})[1], 409)

    def test_a_shot_lands_in_dist_phone(self):
        pl.lend("n1", OWNER, "app", 1)
        png = b"\x89PNG\r\n\x1a\n" + b"x" * 64
        self.answer = {"code": 0, "out": base64.b64encode(png).decode()}
        r, st = pl.use("app", "shot", {})
        self.assertEqual(st, 200, r)
        self.assertEqual((self.tmp / "app" / r["path"]).read_bytes(), png)
        self.assertTrue(pl.view("n1")["shot"].startswith("dist/phone/shot-"))
        self.assertIn("n1:app:", pl.rev())

    def test_install_takes_only_a_dist_apk(self):
        pl.lend("n1", OWNER, "app", 1)
        for bad in ("../x.apk", "src/a.apk", "dist/a.aab", "dist/../../etc.apk"):
            self.assertEqual(pl.use("app", "install", {"file": bad})[1], 400, bad)
        self.assertEqual(pl.use("app", "install", {"file": "dist/missing.apk"})[1], 404)

    def test_an_install_names_the_file_where_the_agent_fetched_it(self):
        # Report #52: a node's record keeps its stores under `reported`, the
        # agent fetched the build into the artifacts store, and adb was
        # pointed at /tmp, which only the top-level read fell back to.
        node = {"reported": {"stores": {"artifacts": {"path": "/var/lib/builderbot/artifacts"}}}}
        self.assertEqual(phone.install_dest(node, "Shebang-DevBoard", "dist/a.apk"),
                         "/var/lib/builderbot/artifacts/Shebang-DevBoard/a.apk")
        self.assertEqual(phone.install_dest({"stores": {"data": {"path": "/d"}}}, "p", "dist/a.apk"), "/d/a.apk")

    def test_a_refusal_is_said_before_its_owner_is_asked(self):
        pl.lend("n1", OWNER, "app", 1)
        (self.tmp / "app" / "dist").mkdir(parents=True)
        (self.tmp / "app" / "dist" / "a.apk").write_bytes(b"apk")
        self.assertIsNone(pl.check("app", "install", {"file": "dist/a.apk"}))
        # The whole path inside the project is the same file.
        self.assertIsNone(pl.check("app", "install", {"file": str(self.tmp / "app" / "dist" / "a.apk")}))
        self.assertEqual(pl.check("app", "install", {"file": "/etc/passwd.apk"})[1], 400)
        self.assertEqual(pl.check("app", "install", {"file": "dist/none.apk"})[1], 404)
        self.assertEqual(pl.check("app", "start", {"pkg": "com.other"})[1], 403)
        self.assertEqual(pl.check("far", "shot", {})[1], 403)          # no lease there
        saved = (phone.leasing, phone.nodes)
        self.addCleanup(lambda: (setattr(phone, "leasing", saved[0]), setattr(phone, "nodes", saved[1])))
        phone.leasing, phone.nodes = pl, None
        session = {"name": "Owner", "uid": "u1", "session": "app"}
        r, st = phone.verb("use", {"op": "install", "args": {"file": "src/a.apk"}}, session, False)
        self.assertEqual(st, 400)
        self.assertNotIn("asked", r)



class Owner(Lease):
    """R120: a phone is its connector's. An administrator may disconnect
    another's; nobody else may. A lent phone's command asks its owner, and
    only the owner's answer runs it, an administrator's included."""

    def test_an_administrator_disconnects_another_persons_phone(self):
        self.assertIn("or an administrator", phone.disconnect("n1", "u2", "Other")["error"])
        self.assertIn("n1", self.recs)
        self.assertTrue(phone.disconnect("n1", "u2", "Admin", admin=True)["ok"])
        self.assertNotIn("n1", self.recs)

    def test_a_lent_phones_command_waits_for_its_owner(self):
        pl.lend("n1", OWNER, "app", 1)
        saved = (phone.leasing, phone.nodes)
        self.addCleanup(lambda: (setattr(phone, "leasing", saved[0]), setattr(phone, "nodes", saved[1])))
        phone.leasing, phone.nodes = pl, None
        self.recs["n1"]["owner_name"] = "Owner"
        ran = []
        real = pl.use
        self.addCleanup(setattr, pl, "use", real)
        pl.use = lambda proj, op, args: (ran.append((proj, op)) or ({"path": "dist/phone/shot-1.png"}, 200)) \
            if op != "status" else real(proj, op, args)
        session = {"name": "Owner", "uid": "u1", "session": "app"}
        r, st = phone.verb("use", {"op": "shot", "args": {}, "why": "see the settings screen"}, session, False)
        self.assertEqual(st, 200)
        rid = r["asked"]
        self.assertEqual(ran, [])                                   # nothing ran yet
        self.assertIn("error", phone.decide(rid, True, "u2", "Admin", admin=True))
        self.assertTrue(phone.decide(rid, True, "u1", "Owner")["ok"])
        for _ in range(50):
            if phone.outcome(rid, "app").get("state") == "done":
                break
            time.sleep(0.02)
        self.assertEqual(ran, [("app", "shot")])
        self.assertIn("shot-1.png", phone.outcome(rid, "app")["out"])


class Scope(unittest.TestCase):
    """report #51: the rows are the asker's scope, matched on the row's id.
    Matched on a `node` key no row has, a session's list came back empty and
    bb phone status said no node carries adb beside a connected phone."""

    def test_a_scoped_asker_sees_its_own_node(self):
        real = phone.payload
        self.addCleanup(setattr, phone, "payload", real)
        phone.payload = lambda *a, **k: {"nodes": [{"id": "n1", "name": "sandbox"}, {"id": "n2", "name": "other"}],
                                         "asks": []}
        out = phone.tab_view("u_1", admin=False, project="app", scope={"n1"})
        self.assertEqual([r["id"] for r in out["nodes"]], ["n1"])
        self.assertEqual(len(phone.tab_view("u_1", admin=True, project="", scope=None)["nodes"]), 2)


if __name__ == "__main__":
    unittest.main()
