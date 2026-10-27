"""Steps that move between items (R168): a step keeps an id of its own, so
one moved, split away or left behind by a drop of one before it is still the
one its first number named; an item folded into another becomes a step of it;
and the list's own references are checked."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import roadmap  # noqa: E402


def write_json(path, data, mode=0o644):
    del mode
    with open(path, "w") as f:
        json.dump(data, f)


class Moves(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        roadmap.configure(write_json=write_json, state=self.tmp)

    def row(self, rid):
        return next((r for r in roadmap.items("p") if r["id"] == rid), None)

    def texts(self, rid):
        return [s["text"] for s in self.row(rid)["steps"]]

    def test_a_step_has_an_id_from_its_item_and_number_for_good(self):
        a = roadmap.add("p", "A", steps=["one", "two", "three"])["item"]["id"]
        self.assertEqual([s["sid"] for s in self.row(a)["steps"]], [[a, 1], [a, 2], [a, 3]])
        roadmap.add_step("p", a, "four")
        self.assertEqual(self.row(a)["steps"][3]["sid"], [a, 4])
        self.assertTrue(roadmap.remove("p", a, step=1).get("ok"))
        roadmap.add_step("p", a, "five")
        self.assertEqual([s["sid"] for s in self.row(a)["steps"]], [[a, 1], [a, 3], [a, 4], [a, 5]],
                         "a dropped number is never handed out again")
        got = roadmap.resolve("p", a, 3)
        self.assertEqual((got["item"]["id"], got["index"], got["moved"]), (a, 1, False), "R.3 is step 2 now")
        self.assertIn("was dropped", roadmap.resolve("p", a, 2)["error"])
        self.assertIn("never had a step 9", roadmap.resolve("p", a, 9)["error"])

    def test_a_step_moved_to_another_item_keeps_everything_and_is_found_by_its_old_number(self):
        a = roadmap.add("p", "A", steps=["one", "two", "three"])["item"]["id"]
        b = roadmap.add("p", "B", steps=["b1"])["item"]["id"]
        roadmap.set_info("p", a, "how", step=1)
        roadmap.set_step_target("p", a, 1, "0.9.0")
        roadmap.step_done("p", a, 1)
        r = roadmap.step_mv("p", a, 1, b)
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(self.texts(a), ["one", "three"])
        self.assertEqual(self.texts(b), ["b1", "two"])
        st = self.row(b)["steps"][1]
        self.assertEqual((st["sid"], st["info"], st["target"], bool(st["done"])), ([a, 2], "how", "0.9.0", True))
        got = roadmap.resolve("p", a, 2)
        self.assertEqual((got["item"]["id"], got["index"], got["moved"]), (b, 1, True))
        self.assertEqual(self.row(a)["moved"][0]["to"], b, "the item it left says where it went")
        acts = [e["act"] for e in roadmap.history("p")]
        self.assertIn("mv-step", acts); self.assertIn("took-step", acts)
        self.assertIn("that is the item it is on", roadmap.step_mv("p", a, 0, a)["error"])
        # At a position: before b1.
        roadmap.step_mv("p", a, 0, b, position=1)
        self.assertEqual(self.texts(b), ["one", "b1", "two"])

    def test_split_moves_steps_to_new_items_that_point_back(self):
        a = roadmap.add("p", "A big one", steps=["s1", "s2", "s3", "s4", "s5"], target="0.9.0")["item"]["id"]
        roadmap.set_info("p", a, "the decisions")
        r = roadmap.split("p", a, [{"text": "Image", "steps": [2, 4]}, {"text": "Stick", "steps": [5], "target": "1.0.0"}])
        self.assertTrue(r.get("ok"), r)
        img, stick = (m["id"] for m in r["made"])
        self.assertEqual(self.texts(a), ["s1", "s3"])
        self.assertEqual((self.texts(img), self.texts(stick)), (["s2", "s4"], ["s5"]))
        self.assertEqual((self.row(img)["target"], self.row(stick)["target"]), ("0.9.0", "1.0.0"), "the old item's target unless its own")
        self.assertIn(f"Split from R{a}", self.row(img)["info"])
        self.assertEqual(roadmap.resolve("p", a, 4)["item"]["id"], img)
        self.assertEqual([m["to"] for m in self.row(a)["moved"]], [img, img, stick])
        self.assertIn("one new item only", roadmap.split("p", a, [{"text": "x", "steps": [1]}, {"text": "y", "steps": [1]}])["error"])
        self.assertIn("has 2 steps", roadmap.split("p", a, [{"text": "x", "steps": [7]}])["error"])

    def test_fold_makes_an_item_a_step_of_another_and_restore_undoes_it(self):
        a = roadmap.add("p", "A", steps=["a1", "a2"])["item"]["id"]
        roadmap.set_info("p", a, "why a")
        b = roadmap.add("p", "B", steps=["b1"])["item"]["id"]
        r = roadmap.fold("p", a, b)
        self.assertTrue(r.get("ok"), r)
        self.assertIsNone(self.row(a))
        self.assertEqual(self.texts(b), ["b1", "A", "a1", "a2"])
        self.assertEqual((self.row(b)["steps"][1]["sid"], self.row(b)["steps"][1]["info"]), ([a, 0], "why a"))
        got = roadmap.resolve("p", a, 0)
        self.assertEqual((got["item"]["id"], got["index"]), (b, 1), "the item itself, as a step")
        self.assertEqual(roadmap.resolve("p", a, 2)["item"]["id"], b)
        self.assertIn("folded into", roadmap.add_step("p", a, "x")["error"])
        self.assertTrue(roadmap.restore("p", a).get("ok"))
        self.assertEqual((self.texts(a), self.texts(b)), (["a1", "a2"], ["b1"]), "back out of B, as they stand")

    def test_fold_into_a_step_adds_the_words_to_its_details(self):
        a = roadmap.add("p", "Vetted crypto", steps=["x1"])["item"]["id"]
        b = roadmap.add("p", "Hardened", steps=["threat model", "crypto", "csp"])["item"]["id"]
        r = roadmap.fold("p", a, b, into_step=1)
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(self.texts(b), ["threat model", "crypto", "x1", "csp"])
        self.assertIn(f"Folded in from R{a}", self.row(b)["steps"][1]["info"])
        self.assertEqual(r["folded"], [b, 2])

    def test_refs_name_what_finds_nothing_and_where_a_moved_one_is(self):
        a = roadmap.add("p", "A", steps=["one", "two"])["item"]["id"]
        b = roadmap.add("p", "B", steps=[f"after R{a} step 2", f"see R{a}.9 and R999"])["item"]["id"]
        self.assertEqual(roadmap.refs("p"), [
            {"where": f"R{b} step 2", "ref": f"R{a}.9", "why": f"R{a} never had a step 9"},
            {"where": f"R{b} step 2", "ref": "R999", "why": "no item R999 here"}])
        roadmap.step_mv("p", a, 1, b)
        moved = [x for x in roadmap.refs("p") if x.get("moved")]
        self.assertEqual(moved, [{"where": f"R{b} step 1", "ref": f"R{a} step 2", "moved": True, "why": f"now R{b} step 3"}])

    def test_the_page_verbs(self):
        a = roadmap.add("p", "A", steps=["one", "two"])["item"]["id"]
        b = roadmap.add("p", "B")["item"]["id"]
        out, status = roadmap.verb("p", "step-mv", {"id": a, "step": 0, "to": b}, {}, live=[], prefix="")
        self.assertEqual((status, self.texts(b)), (200, ["one"]))
        out, status = roadmap.verb("p", "split", {"id": a, "groups": [{"text": "C", "steps": [1]}]}, {}, live=[], prefix="")
        self.assertEqual(status, 200); c = out["made"][0]["id"]
        out, status = roadmap.verb("p", "fold", {"id": c, "into": b}, {}, live=[], prefix="")
        self.assertEqual((status, self.texts(b)), (200, ["one", "C", "two"]))
        out, status = roadmap.verb("p", "refs", {}, {}, live=[], prefix="")
        self.assertEqual((status, out["refs"]), (200, []))

    def test_a_sessions_split_is_held_when_the_gate_asks(self):
        import prefs
        prefs.configure(write_json=write_json, state=self.tmp)
        write_json(os.path.join(self.tmp, "claude-prefs.json"), {"projects": {"p": {"gate": {"roadmap": "ask"}}}})
        a = roadmap.add("p", "A", steps=["one"])["item"]["id"]
        r = roadmap.split("p", a, [{"text": "B", "steps": [1]}], by="claude")
        self.assertTrue(r.get("held"), r)
        self.assertEqual(self.texts(a), ["one"], "nothing moved until approved")


if __name__ == "__main__":
    unittest.main()
