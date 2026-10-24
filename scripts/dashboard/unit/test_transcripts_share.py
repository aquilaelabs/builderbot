"""A person's conversations in a notebook's Sessions view (the operator,
22 Oct): one deleted, or made visible to every session on the project and
then read there as its owner's, never another of theirs."""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import transcripts  # noqa: E402


class Share(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        ws, st = self.tmp / "ws", self.tmp / "state"
        st.mkdir()
        homes = {u: self.tmp / "home" / u for u in ("ann", "bob")}
        saved = {k: getattr(transcripts, k) for k in ("WORKSPACE", "WORKTREES", "root_for", "SHARED", "write_json")}
        self.addCleanup(lambda: [setattr(transcripts, k, v) for k, v in saved.items()])
        transcripts.configure(workspace=ws, root_for=lambda uid: homes[uid], state=st,
                              write_json=lambda p, d: Path(p).write_text(json.dumps(d)))
        old = time.time() - 3600
        for uid, sid in (("ann", "ann-1"), ("ann", "ann-2"), ("bob", "bob-1")):
            d = homes[uid] / transcripts._slug(ws / "web")
            d.mkdir(parents=True, exist_ok=True)
            f = d / f"{sid}.jsonl"
            f.write_text(json.dumps({"type": "user", "message": {"role": "user", "content": f"hello from {sid}"}}) + "\n")
            os.utime(f, (old, old))

    def test_made_visible_others_read_it_as_its_owners(self):
        self.assertIsNone(transcripts.owner_of("bob", "web", "ann-1"), "private: another account's is not found")
        self.assertEqual(transcripts.set_shared("ann", "web", "ann-1", True)[1], 200)
        self.assertEqual(transcripts.owner_of("bob", "web", "ann-1"), "ann")
        self.assertIsNone(transcripts.owner_of("bob", "web", "ann-2"), "only the one made visible")
        self.assertEqual([r["id"] for r in transcripts.visible("bob", "web")], ["ann-1"])
        self.assertEqual([r["id"] for r in transcripts.visible("ann", "web")], [], "not your own twice")
        self.assertTrue(next(r for r in transcripts.mine("ann", ["web"]) if r["id"] == "ann-1")["shared"])
        self.assertIsNone(transcripts.owner_of("bob", "other", "ann-1"), "on its own project alone")
        transcripts.set_shared("ann", "web", "ann-1", False)
        self.assertIsNone(transcripts.owner_of("bob", "web", "ann-1"))

    def test_only_its_person_shares_or_deletes_it(self):
        self.assertEqual(transcripts.set_shared("bob", "web", "ann-1", True)[1], 404)
        self.assertEqual(transcripts.delete("bob", "web", "ann-1")[1], 404)
        transcripts.set_shared("ann", "web", "ann-1", True)
        self.assertEqual(transcripts.delete("ann", "web", "ann-1")[1], 200)
        self.assertEqual([r["id"] for r in transcripts.mine("ann", ["web"])], ["ann-2"])
        self.assertEqual(transcripts.shared("web"), {}, "its visibility goes with it")

    def test_one_still_being_written_is_not_deleted(self):
        f = transcripts._find("ann", "web", "ann-2")
        os.utime(f, None)
        r, st = transcripts.delete("ann", "web", "ann-2")
        self.assertEqual(st, 409)
        self.assertIn("still writing", r["error"])


if __name__ == "__main__":
    unittest.main()
