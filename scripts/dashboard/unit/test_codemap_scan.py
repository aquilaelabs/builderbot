"""bb map's scanners against what the tree really holds: the JS scanner's
words are JavaScript's own, an expression arrow is a function that ends
where its expression does and holds its calls, a shell function ends at
its own `}` and calls what the files around it define, quoted shell text
calls nothing, a selector is read part by part (B576), a file of closures
lists them (B577), and Astro, Vue and Svelte files are read (B578)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))
import codemap  # noqa: E402


def scan(text, path="a.js"):
    sink = codemap.Sink(path)
    {".sh": codemap.scan_sh, ".py": codemap.scan_python}.get(
        Path(path).suffix, codemap.scan_html if Path(path).suffix in (".html", ".astro") else codemap.scan_js)(text, sink)
    return sink


def defs(sink):
    return {(d["name"], d["line"], d["end"]) for d in sink.defs}


def calls(sink):
    return {(c["name"], c["line"], c["caller"]) for c in sink.calls}


class JavaScript(unittest.TestCase):
    def test_another_languages_words_are_names_here(self):
        s = scan("function open(x){ return select(x); }\nconst when = t => t;\nopen(1);\n")
        self.assertIn(("open", 1, 1), defs(s))
        self.assertIn(("when", 2, 2), defs(s))
        self.assertIn(("select", 1, "open"), calls(s))

    def test_a_property_called_interface_is_no_class(self):
        s = scan("function f(net, rn){\n  if (net.interface && rn.interface) g();\n"
                 "  const x = {interface: '', routes: []};\n}\n")
        self.assertEqual({d["name"] for d in s.defs}, {"f"})

    def test_an_async_arrow_is_named_for_what_it_is_assigned_to(self):
        s = scan("function f(){\n  const send = async () => {\n    post();\n  };\n}\n")
        self.assertIn(("send", 2, 4), defs(s))
        self.assertIn(("post", 3, "send"), calls(s))

    def test_an_expression_arrow_ends_with_its_expression_and_holds_its_calls(self):
        s = scan("const pick = (a, b) => [a, b]\n  .map(x => fmt(x))\n  .join(',');\n"
                 "const t = {render: (el) => draw(el), open: () => load()};\n")
        self.assertIn(("pick", 1, 3), defs(s))
        self.assertIn(("fmt", 2, "pick"), calls(s))
        self.assertIn(("draw", 4, "render"), calls(s))
        self.assertIn(("load", 4, "open"), calls(s))

    def test_a_comment_above_a_method_does_not_hide_it(self):
        s = scan("const o = {\n  a: 1,\n  // says what shown does, at length\n  shown(){ go(); },\n};\n")
        self.assertIn(("shown", 4, 4), defs(s))

    def test_a_call_in_a_condition_is_no_method(self):
        s = scan("function f(){\n  if (stage(id, clean(v))){\n    x();\n  }\n}\n")
        self.assertNotIn("clean", {d["name"] for d in s.defs})
        self.assertIn(("clean", 2, "f"), calls(s))

    def test_optional_and_keyword_named_calls_are_calls(self):
        s = scan("function f(k){\n  KINDS[k]?.open?.(k);\n  p.catch(e => 0).finally(done);\n"
                 "  for (const x of (list || [])) use(x);\n}\n")
        names = {c["name"] for c in s.calls}
        self.assertTrue({"open", "catch", "finally", "use"} <= names, names)
        self.assertNotIn("of", names)

    def test_php_closures_are_listed_with_what_they_are_handed_to(self):
        text = "<?php\nadd_action('init', function () {\n  x();\n});\nadd_filter('a', fn() => 'closed');\n"
        with tempfile.TemporaryDirectory() as d:
            Path(d, "f.php").write_text(text)
            idx = codemap.build(d)
            out = codemap.q_defs(idx, "f.php")
        self.assertEqual(out, ["2-4  function (anonymous) passed to add_action",
                               "5  function (anonymous) passed to add_filter"])


class Shell(unittest.TestCase):
    def test_a_nested_function_ends_at_its_own_brace(self):
        s = scan("outer() {\n    inner() {\n        die x\n    }\n    inner\n}\n", "a.sh")
        self.assertEqual(defs(s), {("outer", 1, 6), ("inner", 2, 4)})
        self.assertIn(("inner", 5, "outer"), calls(s))

    def test_quoted_text_calls_nothing_and_a_trap_does(self):
        s = scan('log() { :; }\nrun() { :; }\nf() {\n    log "run this: $(run)"\n'
                 "    echo 'log it'\n    trap 'log' EXIT\n}\n", "a.sh")
        got = {(c["name"], c["line"]) for c in s.calls if c["caller"] == "f"}
        self.assertEqual(got, {("log", 4), ("run", 4), ("log", 6)})

    def test_a_script_calls_what_it_sources_and_a_library_what_sources_it(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "lib").mkdir()
            Path(d, "lib/common.sh").write_text("die() { exit 1; }\n")
            Path(d, "lib/util.sh").write_text("helper() {\n    die nope\n}\n")
            Path(d, "tool").write_text('#!/bin/bash\n. "$(dirname "$0")/lib/common.sh"\n'
                                       '. "$(dirname "$0")/lib/util.sh"\nhelper || die "no"\n')
            idx = codemap.build(d)
            got = {(c["file"], c["name"]) for c in idx["calls"]}
            self.assertIn(("tool", "die"), got)
            self.assertIn(("tool", "helper"), got)
            self.assertIn(("lib/util.sh", "die"), got)
            # a function added to the library is seen called without the
            # script changing
            Path(d, "lib/common.sh").write_text("die() { exit 1; }\nwarn() { :; }\n")
            Path(d, "tool").touch()
            os.utime(Path(d, "lib/common.sh"), (1, 1))
            Path(d, "lib/util.sh").write_text("helper() {\n    warn nope\n}\n")
            idx = codemap.load(d)
            self.assertIn(("lib/util.sh", "warn"), {(c["file"], c["name"]) for c in idx["calls"]})


class Markup(unittest.TestCase):
    def test_a_selector_is_read_part_by_part_and_not_inside_a_value(self):
        self.assertEqual(codemap.strings_draw('a.al-skip[href="#main"]'), [("al-skip", "class")])
        self.assertEqual(codemap.strings_draw("div#x.y > span.k"),
                         [("x", "id"), ("y", "class"), ("k", "class")])
        self.assertEqual(codemap.strings_draw("index.html"), [])

    def test_an_extension_in_python_is_no_class_and_a_file_named_whole_is_named(self):
        s = scan('EXT = ".c"\nPATH = "builderbot-agent.py"\n', "m.py")
        self.assertEqual({(d["what"], d["kind"]) for d in s.draws}, {("builderbot-agent.py", "file")})

    def test_an_astro_component_is_read_with_its_frontmatter(self):
        s = scan("---\nconst t = title();\n---\n<a class=\"al-skip\" href=\"#main\">x</a>\n"
                 "<script>\nfunction go(){ run(); }\n</script>\n", "B.astro")
        self.assertIn(("title", 2, "(top level)"), calls(s))
        self.assertIn(("go", 6, 6), defs(s))
        self.assertIn(("al-skip", "class"), {(d["what"], d["kind"]) for d in s.draws})

    def test_an_empty_answer_names_what_the_map_does_not_read(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "site.css").write_text(".x{}")
            self.assertEqual(codemap.not_read_note(d),
                             ["(not indexed here, so not in that answer: 1 .css; grep them)"])


if __name__ == "__main__":
    unittest.main()
