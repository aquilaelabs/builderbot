"""records.py (R167): every record kind round-trips through JSON, YAML and
Markdown, a document says its format and when it was printed, and an apply
plan names what an edited record would change and never a removal."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import records  # noqa: E402

ITEM = {"id": 12, "text": "A goal", "info": "the why\nin two lines", "target": "0.9.0", "added": 1, "by": "you",
        "sent": 0, "nsteps": 2,
        "steps": [{"text": "one", "sent": 0, "sid": [12, 1], "info": "how\nto"},
                  {"text": "two\n\nmore", "sent": 0, "sid": [12, 2], "done": 5, "target": "1.0.0"}]}
BUG = {"id": 3, "title": "it breaks", "severity": "low", "status": "open", "area": "x", "repro": "do\nthis", "notes": "n"}
RULE = {"name": "tests", "text": "Run them.\nAll of them.", "paths": ["test/"], "by": "claude", "scope": "project"}
PAGE = {"name": "Home", "rev": 4, "text": "# Home\n\nwords"}
ENTRY = {"name": "DASHBOARD_PORT", "file": ".env.example", "line": 32, "kind": "setting", "parent": ""}


class Records(unittest.TestCase):
    def round(self, kind, rec, fmt):
        doc = records.document(kind, [rec], "alpha", as_of=7)
        back = records.load(records.dump(doc, fmt))
        self.assertEqual((back["format"], back["kind"], back.get("as_of")), (records.FORMAT, kind, 7), fmt)
        return back["records"][0]

    def test_every_kind_round_trips_through_every_format(self):
        for kind, rec in (("roadmap", ITEM), ("bugs", BUG), ("rules", RULE), ("wiki", PAGE), ("map", ENTRY)):
            for fmt in ("json", "yaml", "markdown"):
                got = self.round(kind, rec, fmt)
                for k, v in rec.items():
                    # Markdown writes no line for an empty field, and none is what it is.
                    self.assertEqual(got.get(k) or "", v or "", f"{kind} {fmt} {k}")

    def test_a_bare_list_or_one_record_is_a_document(self):
        self.assertEqual(records.load('[{"text": "x"}]')["records"], [{"text": "x"}])
        self.assertEqual(records.load("text: x\n")["records"], [{"text": "x"}])
        self.assertEqual(records.load("## R4 a title\n\n- target: 0.9.0\n\n1. first\n2. second\n")["records"],
                         [{"text": "a title", "id": 4, "target": "0.9.0", "steps": [{"text": "first"}, {"text": "second"}]}])

    def test_a_newer_format_is_refused(self):
        with self.assertRaises(ValueError):
            records.load('{"format": 99, "records": []}')

    def test_an_apply_plan_names_the_changes_and_never_a_removal(self):
        rows = [ITEM]
        edited = {"id": 12, "text": "A goal, reworded", "target": "0.9.0",
                  "steps": [{"sid": [12, 1], "text": "one changed", "info": "how\nto"}, {"text": "three"}]}
        changes, adds = records.apply_plan({"records": [edited]}, rows)
        self.assertEqual(changes, [(12, "text", None, "A goal, reworded"), (12, "text", 0, "one changed")])
        self.assertEqual(adds, [(12, "three")])
        with self.assertRaises(ValueError):
            records.apply_plan({"records": [{"id": 99, "text": "x"}]}, rows)


if __name__ == "__main__":
    unittest.main()
