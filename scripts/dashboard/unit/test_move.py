"""Moving a controller to another home (R90 step 12, move.py): the bundle
sealed under a token shown once, the nodes' challenges, the restore held to
the version gate and refused under another token, the old home marked
moved, and what the new home answers a node's knock; and the second pass
(R175): the move armed with no life and the bundle packed fresh, a late
node handed its challenge after the move, the landing told both ways under
the move key, the pull's proof, the pieces, and the nodes not yet here."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import move     # noqa: E402
import signing  # noqa: E402


def write_json(path, obj, mode=0o644):
    with open(path, "w") as f:
        json.dump(obj, f)


class Move(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state = self.tmp / "config"
        self.ws = self.tmp / "workspace"
        self.secrets = self.tmp / "secrets"
        self.store = self.tmp / "elsewhere" / "gitrelay"
        for d in (self.state / "logs", self.state / "apps", self.ws / "alpha" / ".git", self.secrets, self.store / "alpha.git"):
            d.mkdir(parents=True)
        (self.state / "users.json").write_text('{"users": {"ann": {}}}')
        (self.state / "logs" / "old.log").write_text("not moved")
        (self.ws / "alpha" / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
        (self.secrets / "deploy.env").write_text("DEPLOY=1\n")
        (self.store / "alpha.git" / "HEAD").write_text("bare\n")
        self.configure(self.state, bare=False)

    def configure(self, state, bare, seen=None, url="https://old.example/"):
        self.audits = []
        move.configure(state=state, workspace=self.ws, secrets_dir=str(self.secrets), write_json_fn=write_json,
                       seal_fn=signing.seal, open_fn=signing.open_with, state_version_fn=lambda: 16, build_version_fn=lambda: "0.9.0",
                       install_key_fn=lambda: b"k" * 32, store_paths_fn=lambda: {"gitrelay": str(self.store), "logs": str(self.tmp / "logs")},
                       page_url_fn=lambda: url, node_ids_fn=lambda: ["n_1", "n_2"], bare_metal_fn=lambda: bare,
                       node_seen_fn=lambda: dict(seen or {}), node_name_fn=lambda nid: {"n_1": "alpha", "n_2": "beta"}.get(nid, nid),
                       audit_fn=lambda who, what, detail: self.audits.append((what, detail)))

    def test_the_bundle_moves_the_state_and_the_nodes_follow(self):
        r = move.prepare("user:ann", "https://new.example", repos=True, carry_key=True)
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(r["counts"]["state"], 2, "the record and the users; the logs and the apps stay behind")
        self.assertEqual((r["counts"]["repos"], r["counts"]["secrets"], r["counts"]["gitrelay"], r["counts"]["install_key"]), (1, 1, 1, 1))
        token = r["token"]
        st = move.status()
        self.assertTrue(st["prepared"] and st["to"] == "https://new.example" and st["carries_key"] and st["repos"])
        self.assertEqual((st["heard"], st["nodes"], st["stores"]), (0, 2, ["gitrelay"]), "nobody has heard it yet; the logs store is off by default")
        self.assertTrue(move.bundle_path().is_file())
        raw = move.bundle_path().read_bytes()
        self.assertNotIn(b'"users"', raw, "the state is sealed, not readable")
        self.assertNotIn(token.encode(), (self.state / "move.json").read_bytes(), "the token is never kept")
        # The nodes are told: an address and a challenge each.
        fn = move.for_node("n_1")
        self.assertEqual(fn["url"], "https://new.example")
        self.assertEqual(len(fn["expect"]), 64)
        self.assertNotEqual(fn["expect"], move.for_node("n_2")["expect"])
        self.assertEqual(move.answer_for("n_1"), "", "nothing is answered before the bundle lands")
        # The new home: another token is refused, an older build is refused,
        # the right token lands the state and answers the nodes' knocks.
        new_state = self.tmp / "new-config"
        new_state.mkdir()
        (new_state / "fresh.json").write_text("{}")
        self.configure(new_state, bare=True)
        self.assertIn("not this bundle's", move.restore(str(move_bundle := self.tmp / "config" / "move" / r["bundle"]), "wrong-token",
                                                         state_dir=new_state)["error"])
        self.assertIn("never lands on an older build", move.restore(str(move_bundle), token, state_dir=new_state, build_state_version=15)["error"])
        got = move.restore(str(move_bundle), token, state_dir=new_state, workspace_dir=self.tmp / "new-ws", secrets_dir=self.tmp / "new-secrets")
        self.assertTrue(got.get("ok"), got)
        self.assertEqual(got["from"], "https://old.example/")
        self.assertEqual(got["nodes"], ["n_1", "n_2"])
        self.assertTrue((new_state / "users.json").is_file() and not (new_state / "logs").exists())
        self.assertTrue((self.tmp / "new-ws" / "alpha" / ".git" / "HEAD").is_file())
        self.assertTrue((self.tmp / "new-secrets" / "deploy.env").is_file())
        self.assertEqual((new_state / ".install-key" / "key").read_bytes(), b"k" * 32)
        self.assertTrue(Path(got["moved_aside"]).is_dir() and (Path(got["moved_aside"]) / "fresh.json").is_file(), "what was there is moved aside")
        self.assertTrue((self.store / "alpha.git" / "HEAD").is_file(), "the store landed where the record names it")
        self.assertEqual(move.answer_for("n_1"), fn["expect"], "the knock is answered with the challenge the node holds")
        self.assertEqual(move.restored()["from"], "https://old.example/")
        self.assertFalse(move.status()["prepared"], "landed, the move is used")
        self.assertEqual(move.for_node("n_1"), {}, "the new home tells its nodes of no move: the record came with the bundle")
        # The nodes not yet here (R175 step 3): both, until each says hello
        # after the landing; each with its follow line.
        self.configure(new_state, bare=True, seen={"n_1": 1}, url="https://new.example/")
        nh = move.not_yet_here()
        self.assertEqual([x["name"] for x in nh], ["alpha", "beta"])
        self.assertEqual(nh[0]["line"], f"builderbot-agent follow https://new.example/ {fn['expect']}")
        import time as _t
        self.configure(new_state, bare=True, seen={"n_1": int(_t.time()) + 5}, url="https://new.example/")
        self.assertEqual([x["id"] for x in move.not_yet_here()], ["n_2"])
        # The old home, marked moved: read-only, saying where; and a late
        # node still hears the move with its challenge (R175 step 2).
        self.configure(self.state, bare=False)
        self.assertEqual(move.mark_moved("https://new.example")["to"], "https://new.example")
        self.assertEqual(move.moved_to(), "https://new.example")
        fn2 = move.challenge(move.key_of(token), "n_2")
        self.assertEqual(move.for_node("n_2"), {"url": "https://new.example", "expect": fn2})
        self.assertEqual(move.answer_for("n_2"), "", "the old home answers no knock")
        self.assertIn("moved already", move.prepare("user:ann", "https://x.example")["error"])
        self.assertIn("not withdrawn", move.forget("user:ann")["error"])

    def test_a_prepared_move_is_forgotten_and_a_bad_address_refused(self):
        self.assertIn("http://", move.prepare("user:ann", "new.example")["error"])
        r = move.prepare("user:ann", "")
        self.assertTrue(r.get("ok"), "an address may be named later")
        self.assertEqual(move.for_node("n_1"), {}, "no address yet: the nodes are told nothing")
        self.assertTrue(move.forget("user:ann")["ok"])
        self.assertIsNone(move.bundle_path())
        self.assertIn("no move", move.forget("user:ann")["error"])
        m, why = move.read_manifest(str(self.state / "users.json"))
        self.assertIsNone(m)
        self.assertIn("not a BuilderBot move bundle", why)


    def test_the_landing_is_told_both_ways_and_the_pull_is_proved(self):
        r = move.prepare("user:ann", "https://new.example")
        token, key = r["token"], move.key_of(r["token"])
        th = move.token_hash(token)
        # The old side taking the new one's word: the wrong hash, a wrong
        # proof, then the right one, which marks this controller moved.
        self.assertEqual(move.take_landing({"hash": "x", "at": 5, "proof": "y"})[1], 403)
        self.assertEqual(move.take_landing({"hash": th, "at": 5, "proof": move.landed_proof(key, 6)})[1], 403)
        out, st = move.take_landing({"hash": th, "at": 5, "proof": move.landed_proof(key, 5), "here": "https://new.example"})
        self.assertEqual((st, out["moved"], out["to"]), (200, True, "https://new.example"))
        self.assertEqual((move.status()["how"], move.status()["landed_at"]), ("told", 5))
        self.assertEqual(self.audits[-1][0], "moved-by-landing")
        self.assertEqual(move.take_landing({"hash": th, "at": 5, "proof": move.landed_proof(key, 5)})[0]["moved"], True, "told twice is one answer")
        # The pull's proof (R175 step 5): refused after the move, so a
        # fresh old controller is armed for it.
        self.assertEqual(move.serve_fetch({"hash": th, "nonce": "n1", "proof": move.fetch_proof(key, "n1")})[2], 410)
        self.configure(self.state, bare=False)
        move.forget("user:ann") if not move.moved_to() else None
        state2 = self.tmp / "config2"
        shutil.copytree(self.state, state2, ignore=shutil.ignore_patterns("move.json", "move"))
        self.configure(state2, bare=False)
        r = move.prepare("user:ann", "")
        token, key, th = r["token"], move.key_of(r["token"]), move.token_hash(r["token"])
        self.assertEqual(move.serve_fetch({"hash": th, "nonce": "n1", "proof": "bad"})[2], 403)
        path, why, st = move.serve_fetch({"hash": th, "nonce": "n1", "proof": move.fetch_proof(key, "n1")})
        self.assertTrue(st == 200 and Path(path).is_file() and Path(path).name == move.status()["bundle"], (path, why))
        self.assertEqual(move.serve_fetch({"hash": th, "nonce": "n1", "proof": move.fetch_proof(key, "n1")})[2], 403, "a nonce is good once")
        self.assertEqual(self.audits[-1][0], "move-bundle-pulled")
        # The bundle is packed fresh: a record written after Prepare is in it.
        (state2 / "later.json").write_text("{}")
        path, why, st = move.serve_fetch({"hash": th, "nonce": "n2", "proof": move.fetch_proof(key, "n2")})
        m, _ = move.read_manifest(path)
        self.assertEqual(m["counts"]["state"], 3, "the record, the users and the later file")
        # The new side answering the old one's asking (R175 step 4), once
        # the bundle landed there.
        new_state = self.tmp / "new-config"
        new_state.mkdir()
        self.configure(new_state, bare=True, url="https://new.example/")
        got = move.restore(path, token, state_dir=new_state, workspace_dir=self.tmp / "new-ws", secrets_dir=self.tmp / "new-secrets")
        self.assertTrue(got.get("ok"), got)
        self.assertEqual(move.answer_asked({"hash": th, "nonce": "q", "proof": "bad"})[1], 403)
        out, st = move.answer_asked({"hash": th, "nonce": "q", "proof": move.asked_proof(key, "q")})
        self.assertEqual((st, out["ok"], out["here"]), (200, True, "https://new.example/"))
        self.assertEqual(out["landed_at"], move.restored()["restored_at"])
        self.assertEqual(move.restored()["from"], "https://old.example/")
        self.assertFalse(move.tell_old(force=True), "the old address does not answer from here; told again next tick")
        self.assertIn("tell_error", move.restored())

    def test_the_pieces_say_their_sizes_and_the_ticks_hold(self):
        pcs = {p["key"]: p for p in move.pieces()}
        self.assertTrue(pcs["state"]["fixed"] and pcs["state"]["on"] and pcs["state"]["size"] > 0)
        self.assertTrue(pcs["store:gitrelay"]["on"] and not pcs["store:logs"]["on"], "the logs store is off unless ticked")
        self.assertFalse(pcs["repos"]["on"] or pcs["install_key"]["on"])
        self.assertEqual(pcs["repos"]["size"], len("ref: refs/heads/main\n"))
        (self.tmp / "logs").mkdir()
        (self.tmp / "logs" / "a.log").write_text("x")
        r = move.prepare("user:ann", "", stores=["gitrelay", "logs"])
        self.assertEqual((r["counts"].get("gitrelay"), r["counts"].get("logs")), (1, 1))
        self.assertEqual(move.status()["stores"], ["gitrelay", "logs"])
        self.assertTrue(move.forget("user:ann")["ok"])
        r = move.prepare("user:ann", "", stores=[])
        self.assertNotIn("gitrelay", r["counts"], "no store ticked, none carried")


if __name__ == "__main__":
    unittest.main()
