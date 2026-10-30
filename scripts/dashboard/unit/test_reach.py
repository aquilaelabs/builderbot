"""The bell's rows sent elsewhere (R149, reach.py): destinations kept per
person with their secrets sealed, each channel's message shape, the tick
sending what is new to each destination and holding a repeat while the
row's key is unchanged, the quiet window, and a test send."""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import reach      # noqa: E402
import signing    # noqa: E402
import statefile  # noqa: E402

KEY = b"r" * 32
UID = "u_0000000a"


class Hook(BaseHTTPRequestHandler):
    got = []

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        Hook.got.append({"path": self.path, "headers": dict(self.headers), "body": self.rfile.read(n)})
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format, *args):
        del format, args


class Reach(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.was = signing.MASTER, signing.PREVIOUS
        signing.MASTER, signing.PREVIOUS = KEY, None
        self.addCleanup(lambda: setattr(signing, "MASTER", self.was[0]) or setattr(signing, "PREVIOUS", self.was[1]))
        reach.configure(state=self.tmp, write_json=statefile.write_json, seal=signing.seal, unseal=signing.unseal,
                        sealing=lambda: signing.MASTER is not None, smtp_settings=lambda: {})
        Hook.got = []
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Hook)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.shutdown)
        self.url = f"http://127.0.0.1:{self.srv.server_port}/hook"

    def test_a_destination_is_kept_with_its_secret_sealed(self):
        self.assertIn("one of", reach.set_dest(UID, {"kind": "pager"})["error"])
        self.assertIn("needs", reach.set_dest(UID, {"kind": "ntfy", "fields": {"server": "https://ntfy.sh"}})["error"])
        r = reach.set_dest(UID, {"kind": "ntfy", "name": "my phone", "fields": {"server": "https://ntfy.sh", "topic": "bb", "token": "tk_secret"},
                                 "kinds": ["asks", "ci"], "quiet": {"from": "22:00", "to": "07:00"}})
        self.assertTrue(r.get("ok"), r)
        d = r["dest"]
        self.assertEqual((d["kind"], d["name"], d["kinds"], d["quiet"], d["fields"]["token"], d["fields"]["topic"]),
                         ("ntfy", "my phone", ["asks", "ci"], {"from": "22:00", "to": "07:00"}, "set", "bb"))
        raw = open(os.path.join(self.tmp, "reach.json")).read()
        self.assertNotIn("tk_secret", raw, "sealed under the install key")
        self.assertIn("bbseal:", raw)
        self.assertEqual(oct(os.stat(os.path.join(self.tmp, "reach.json")).st_mode & 0o777), "0o600")
        # Changed with the secret left empty: it keeps what it had.
        r2 = reach.set_dest(UID, {"id": d["id"], "kind": "ntfy", "name": "phone", "fields": {"server": "https://ntfy.sh", "topic": "bb2"}, "kinds": ["asks"]})
        self.assertEqual((r2["dest"]["name"], r2["dest"]["fields"]["topic"], r2["dest"]["fields"]["token"]), ("phone", "bb2", "set"))
        self.assertEqual(len(reach.list_for(UID)), 1)
        self.assertIn("quiet window", reach.set_dest(UID, {"kind": "discord", "fields": {"url": "https://x"}, "quiet": {"from": "25:00", "to": "1"}})["error"])
        self.assertEqual(reach.seal_all(again=True), 1)
        self.assertTrue(reach.remove(UID, d["id"])["ok"])
        self.assertIn("no such", reach.remove(UID, d["id"])["error"])
        self.assertEqual(reach.list_for(UID), [])

    def test_the_tick_sends_what_is_new_and_holds_a_repeat(self):
        d = reach.set_dest(UID, {"kind": "webhook", "name": "hook", "fields": {"url": self.url, "header": "X-Key: abc"}, "kinds": ["asks", "needs"]})["dest"]
        rows = [{"key": "ask:1", "kind": "asks", "title": "root on box: needs your answer", "text": "apt install x", "url": ""},
                {"key": "need:agent:n1@2", "kind": "needs", "title": "Agent update on box", "text": "runs 1 and 2 is out", "url": ""},
                {"key": "ci:web@9", "kind": "ci", "title": "CI failing in web", "text": "", "url": ""}]
        n = reach.tick(lambda uid: rows, {UID}, "https://bb.example/")
        self.assertEqual(n, 1)
        self.assertEqual(len(Hook.got), 1)
        body = json.loads(Hook.got[0]["body"])
        self.assertEqual(body["title"], "BuilderBot: 2 things for you")
        self.assertEqual(len(body["lines"]), 2, "the CI row is not a kind this destination takes")
        self.assertEqual(Hook.got[0]["headers"].get("X-Key"), "abc")
        self.assertEqual(body["url"], "https://bb.example/")
        # The same rows again: nothing new, nothing sent.
        self.assertEqual(reach.tick(lambda uid: rows, {UID}), 0)
        # A row left and came back: sent again; a new row alone goes with its own title and link.
        self.assertEqual(reach.tick(lambda uid: rows[1:], {UID}), 0)
        rows2 = [rows[1], {"key": "ask:2", "kind": "asks", "title": "release web v1: needs your answer", "text": "", "url": "https://bb.example/#/p"}]
        self.assertEqual(reach.tick(lambda uid: rows2, {UID}), 1)
        body = json.loads(Hook.got[-1]["body"])
        self.assertEqual((body["title"], body["url"]), ("release web v1: needs your answer", "https://bb.example/#/p"))
        last = reach.list_for(UID)[0]["last"]
        self.assertTrue(last["ok"] and last["rows"] == 1)
        # A destination that fails says so on its row and is tried again.
        bad = reach.set_dest(UID, {"kind": "webhook", "name": "dead", "fields": {"url": "http://127.0.0.1:9/x"}, "kinds": ["asks"]})["dest"]
        reach.tick(lambda uid: rows2, {UID})
        self.assertFalse(next(x for x in reach.list_for(UID) if x["id"] == bad["id"])["last"]["ok"])
        del d

    def test_the_quiet_window_holds_and_a_test_send(self):
        reach.set_dest(UID, {"kind": "webhook", "name": "hook", "fields": {"url": self.url}, "quiet": {"from": "00:00", "to": "23:59"}})
        rows = [{"key": "ask:1", "kind": "asks", "title": "x", "text": "", "url": ""}]
        self.assertEqual(reach.tick(lambda uid: rows, {UID}), 0, "inside the window: held")
        self.assertTrue(reach._in_quiet({"from": "22:00", "to": "07:00"}, time.mktime((2026, 1, 1, 23, 30, 0, 0, 0, -1))))
        self.assertFalse(reach._in_quiet({"from": "22:00", "to": "07:00"}, time.mktime((2026, 1, 1, 12, 0, 0, 0, 0, -1))))
        self.assertTrue(reach._in_quiet({"from": "22:00", "to": "07:00"}, time.mktime((2026, 1, 1, 6, 59, 0, 0, 0, -1))))
        did = reach.list_for(UID)[0]["id"]
        self.assertTrue(reach.test(UID, did, "ann")["ok"])
        self.assertIn("test from BuilderBot for ann", json.loads(Hook.got[-1]["body"])["lines"][0])
        self.assertIn("no mail server", reach.test(UID, reach.set_dest(UID, {"kind": "email", "fields": {"to": "a@b"}})["dest"]["id"])["error"])

    def test_each_preset_posts_its_shape(self):
        for kind, fields, check in (
                ("ntfy", {"server": self.url, "topic": "t", "token": "k"}, lambda g: g["path"].endswith("/hook/t") and g["headers"].get("Authorization") == "Bearer k" and g["headers"].get("Title")),
                ("gotify", {"server": self.url, "token": "g"}, lambda g: g["path"].endswith("/hook/message") and g["headers"].get("X-Gotify-Key") == "g" and json.loads(g["body"])["title"]),
                ("discord", {"url": self.url}, lambda g: json.loads(g["body"])["content"].startswith("**")),
                ("slack", {"url": self.url}, lambda g: json.loads(g["body"])["text"].startswith("*"))):
            Hook.got = []
            d = reach.set_dest(UID, {"kind": kind, "fields": fields})["dest"]
            self.assertTrue(reach.test(UID, d["id"])["ok"], kind)
            self.assertTrue(check(Hook.got[-1]), kind)


if __name__ == "__main__":
    unittest.main()
