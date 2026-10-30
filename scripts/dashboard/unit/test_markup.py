"""markup.py (R167): YAML's subset written and read back as itself, the
keys of each data file with their lines, Markdown by its headings, and a
file that does not parse said rather than crashed."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))
import markup  # noqa: E402


class Yaml(unittest.TestCase):
    def test_a_document_round_trips(self):
        doc = {"format": 1, "kind": "roadmap", "records": [
            {"id": 12, "text": "a: thing", "info": "two\nlines", "tail": "ends\n",
             "steps": [{"text": "one", "sid": [12, 1], "done": 0}, {"text": "yes", "sid": [12, 2]}],
             "target": "0.9.0", "n": None, "ok": True, "f": 1.5, "empty": [], "none": {}}]}
        self.assertEqual(markup.yaml_load(markup.yaml_dump(doc)), doc)

    def test_strings_that_would_read_as_something_else_are_quoted(self):
        for s in ("yes", "null", "12", "1.5", "- a", "a: b", "#x", "", " pad", "[1]", "{a: 1}", "x #y"):
            self.assertEqual(markup.yaml_load(markup.yaml_dump({"k": s}))["k"], s, s)

    def test_what_a_person_writes_is_read(self):
        text = ("# a comment\nname: web  # trailing\nports:\n  - 80\n  - \"443\"\nenv:\n  KEY: value\n"
                "  OTHER:\nnote: |\n  first\n  second\nlist: [a, b]\nmap: {x: 1}\nquoted: 'it''s'\n")
        self.assertEqual(markup.yaml_load(text), {
            "name": "web", "ports": [80, "443"], "env": {"KEY": "value", "OTHER": None},
            "note": "first\nsecond\n", "list": ["a", "b"], "map": {"x": 1}, "quoted": "it's"})

    def test_a_bad_file_is_an_error_with_its_line(self):
        with self.assertRaises(markup.MarkupError) as got:
            markup.yaml_load("a: 1\n  b: 2\n")
        self.assertIn("line 2", str(got.exception))


class Keys(unittest.TestCase):
    def test_each_kind_gives_its_keys_with_lines(self):
        self.assertEqual(markup.keys_of('{\n "a": {"b": 1},\n "c": 2\n}', ".json"), [("a", 2), ("a/b", 2), ("c", 3)])
        self.assertEqual(markup.keys_of("services:\n  web:\n    environment:\n      PORT: 1\n", ".yml"),
                         [("services", 1), ("services/web", 2), ("services/web/environment", 3), ("services/web/environment/PORT", 4)])
        self.assertEqual(markup.keys_of("[tool]\nname = 'x'\n", ".toml"), [("tool/name", 2)])
        self.assertEqual(markup.keys_of('<C>\n <Config Name="Port" Target="DASHBOARD_PORT"/>\n</C>', ".xml"), [("DASHBOARD_PORT", 2)])
        self.assertEqual(markup.keys_of("A=1\n# c\nexport B=2\n", ".example"), [("A", 1), ("B", 3)])
        self.assertEqual(markup.keys_of("# T\n```\n# no\n```\n## U\n", ".md"), [("T", 1), ("U", 5)])
        self.assertEqual(markup.keys_of("whatever", ".css"), [])

    def test_a_file_that_does_not_parse_is_said(self):
        for text, suffix in (("{", ".json"), ("a: [", ".toml"), ("<a>", ".xml")):
            with self.assertRaises(markup.MarkupError):
                markup.keys_of(text, suffix)


class Markdown(unittest.TestCase):
    def test_sections_carry_their_bodies(self):
        got = markup.md_sections("# A\nintro\n\n## B\nbody b\n### C\nbody c\n")
        self.assertEqual([(l, t, n, b) for l, t, n, b in got],
                         [(1, "A", 1, "intro"), (2, "B", 4, "body b"), (3, "C", 6, "body c")])


if __name__ == "__main__":
    unittest.main()
