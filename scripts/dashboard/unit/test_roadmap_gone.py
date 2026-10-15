"""An item that is not on the list says why (B737): finished (its last
step done, or ticked off), dropped, or never there, rather than 'no such
item' for all three."""
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


class Gone(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        roadmap.configure(write_json=write_json, state=self.tmp)

    def test_a_step_after_the_last_one_says_the_item_is_done(self):
        r = roadmap.add("alpha", "a plan", by="claude", steps=["one", "two"])
        rid = r["item"]["id"]
        self.assertTrue(roadmap.step_done("alpha", rid, 0).get("ok"))
        last = roadmap.step_done("alpha", rid, 1)
        self.assertTrue(last.get("finished"), last)
        again = roadmap.step_done("alpha", rid, 1)
        self.assertIn(f"R{rid} is done already", again["error"])

    def test_a_plan_finished_by_its_last_step_keeps_its_steps(self):
        # B767: the Finished section showed it as the words alone.
        rid = roadmap.add("alpha", "a plan", by="claude", steps=["one", "two"])["item"]["id"]
        roadmap.step_done("alpha", rid, 0)
        roadmap.step_done("alpha", rid, 1)
        done = next(r for r in roadmap.finished("alpha") if r["id"] == rid)
        self.assertEqual([st["text"] for st in done["steps"]], ["one", "two"])

    def test_a_finished_item_keeps_its_words_and_details_open(self):
        # B766: finished is how it shows, not a lock. Its details and its
        # words can still be put right, and it stays under Finished with them;
        # the verbs about doing the work still say it is done.
        rid = roadmap.add("alpha", "a plan", by="claude", steps=["one"])["item"]["id"]
        self.assertTrue(roadmap.step_done("alpha", rid, 0).get("finished"))
        self.assertTrue(roadmap.set_info("alpha", rid, "as built: here", step=0).get("ok"))
        self.assertTrue(roadmap.set_info("alpha", rid, "the item's own note").get("ok"))
        self.assertTrue(roadmap.edit("alpha", rid, "a plan, said better").get("ok"))
        done = next(r for r in roadmap.finished("alpha") if r["id"] == rid)
        self.assertEqual((done["text"], done.get("info"), done["steps"][0].get("info")),
                         ("a plan, said better", "the item's own note", "as built: here"))
        self.assertIn(f"R{rid} is done already", roadmap.step_done("alpha", rid, 0)["error"])
        self.assertFalse(any(r["id"] == rid for r in roadmap.load()["projects"].get("alpha") or []),
                         "and it is still off the open list")

    def test_one_kept_without_its_row_is_put_back_together_from_the_log(self):
        # Finished by its last step before B767, an item's done event held the
        # words alone; its steps come back from the log, and its details can
        # be written into them.
        rid = roadmap.add("alpha", "older plan", by="claude", steps=["made with it"])["item"]["id"]
        roadmap.add_step("alpha", rid, "added after")
        roadmap.set_info("alpha", rid, "the step's note", step=1)
        roadmap.step_done("alpha", rid, 0)
        roadmap.step_done("alpha", rid, 1)
        d = roadmap.load()
        for e in d["history"]["alpha"]:
            if e.get("act") == "done" and e.get("step") is None:
                e.pop("row", None)            # as an event from before B767 reads
        roadmap.save(d)
        done = next(r for r in roadmap.finished("alpha") if r["id"] == rid)
        self.assertEqual([st["text"] for st in done["steps"]], ["step 1 (its words were not kept)", "added after"])
        self.assertEqual(done["steps"][1].get("info"), "the step's note")
        self.assertTrue(all(st.get("done") for st in done["steps"]))
        self.assertTrue(roadmap.set_info("alpha", rid, "as built", step=1).get("ok"))
        self.assertEqual(next(r for r in roadmap.finished("alpha") if r["id"] == rid)["steps"][1].get("info"), "as built")

    def test_an_empty_row_an_older_build_saved_gets_its_steps_back(self):
        # 15 Oct: a note written to such an item by the build before the
        # rebuild saved a row with no steps into its done event; the steps the
        # log knows join it, its note stays.
        rid = roadmap.add("alpha", "plan", by="claude")["item"]["id"]
        roadmap.add_step("alpha", rid, "only step")
        roadmap.step_done("alpha", rid, 0)
        d = roadmap.load()
        for e in d["history"]["alpha"]:
            if e.get("act") == "done" and e.get("step") is None:
                e["row"] = {"id": rid, "text": "plan", "steps": [], "info": "item note"}
        roadmap.save(d)
        done = next(r for r in roadmap.finished("alpha") if r["id"] == rid)
        self.assertEqual(([st["text"] for st in done["steps"]], done.get("info")), (["only step"], "item note"))
        self.assertTrue(roadmap.set_info("alpha", rid, "step note", step=0).get("ok"))

    def test_a_finished_item_reopens_as_it_was(self):
        # More work found on a finished item is its own step, not a new item
        # naming the old one (the operator, 15 Oct).
        rid = roadmap.add("alpha", "plan", by="claude", steps=["one"])["item"]["id"]
        roadmap.set_info("alpha", rid, "a note", step=0)
        roadmap.step_done("alpha", rid, 0)
        r = roadmap.reopen("alpha", rid, by="claude")
        self.assertTrue(r.get("ok"), r)
        row = next(x for x in roadmap.items("alpha") if x["id"] == rid)
        self.assertEqual((row["steps"][0]["text"], row["steps"][0].get("info"), bool(row["steps"][0].get("done"))),
                         ("one", "a note", True))
        self.assertFalse(any(x["id"] == rid for x in roadmap.finished("alpha")), "no longer under Finished")
        self.assertTrue(roadmap.add_step("alpha", rid, "the walk found later").get("ok"))
        self.assertIn("is on the list", roadmap.reopen("alpha", rid)["error"])
        roadmap.step_done("alpha", rid, 1)
        self.assertTrue(any(x["id"] == rid for x in roadmap.finished("alpha")), "finished again by its new last step")

    def test_finished_items_outlive_the_trim(self):
        # B768: the log keeps its last MAX_HISTORY events and every finished
        # item, since a done event is the finished item.
        old = roadmap.add("alpha", "old work", by="claude")["item"]["id"]
        roadmap.tick("alpha", old)
        for k in range(roadmap.MAX_HISTORY + 20):
            roadmap.add("alpha", f"filler {k}", by="claude")
            d = roadmap.load(); d["projects"]["alpha"] = []; roadmap.save(d)
        self.assertTrue(any(x["id"] == old for x in roadmap.finished("alpha")))

    def test_a_dropped_one_and_one_never_there_say_so(self):
        rid = roadmap.add("alpha", "to drop", by="claude")["item"]["id"]
        roadmap.remove("alpha", rid, why="not needed", by="operator")
        self.assertIn(f"R{rid} was dropped", roadmap.step_done("alpha", rid, 0)["error"])
        self.assertEqual(roadmap.step_done("alpha", 4242, 0)["error"], "no item R4242 on this list")


if __name__ == "__main__":
    unittest.main()
