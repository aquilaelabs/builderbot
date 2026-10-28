"""Moving a controller to another home (R90 step 12, move.py): the bundle
sealed under a token shown once, the nodes' challenges, the restore held to
the version gate and refused under another token, the old home marked
moved, and what the new home answers a node's knock."""
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

    def configure(self, state, bare):
        move.configure(state=state, workspace=self.ws, secrets_dir=str(self.secrets), write_json_fn=write_json,
                       seal_fn=signing.seal, open_fn=signing.open_with, state_version_fn=lambda: 16, build_version_fn=lambda: "0.9.0",
                       install_key_fn=lambda: b"k" * 32, store_paths_fn=lambda: {"gitrelay": str(self.store)},
                       page_url_fn=lambda: "https://old.example/", node_ids_fn=lambda: ["n_1", "n_2"], bare_metal_fn=lambda: bare)

    def test_the_bundle_moves_the_state_and_the_nodes_follow(self):
        r = move.prepare("user:ann", "https://new.example", repos=True, carry_key=True)
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(r["counts"]["state"], 2, "the record and the users; the logs and the apps stay behind")
        self.assertEqual((r["counts"]["repos"], r["counts"]["secrets"], r["counts"]["gitrelay"], r["counts"]["install_key"]), (1, 1, 1, 1))
        token = r["token"]
        st = move.status()
        self.assertTrue(st["prepared"] and st["to"] == "https://new.example" and st["carries_key"] and st["repos"])
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
        # The old home, marked moved: read-only, saying where.
        self.configure(self.state, bare=False)
        self.assertEqual(move.mark_moved("https://new.example")["to"], "https://new.example")
        self.assertEqual(move.moved_to(), "https://new.example")
        self.assertIn("moved already", move.prepare("user:ann", "https://x.example")["error"])

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


if __name__ == "__main__":
    unittest.main()
